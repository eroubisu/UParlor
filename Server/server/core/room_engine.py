"""
房间制游戏引擎基座

把各游戏共用的"房间外壳"集中在一处：房间生命周期、成员与准备、房主指令、
断线/退出、Bot 调度、通知广播、结算编排。具体游戏只实现玩法钩子。

位置惯例: lobby（大厅） / {game_key}#房间号（房间内）

子类需要声明:
    game_key, display_name      — 与 GAME_INFO.id / name 一致
    room_class, min_players     — 房间类与硬性最少人数
    _GLOBAL_COMMANDS, _COMMAND_MAP — 指令路由（见 BaseGameEngine）

子类实现的玩法钩子:
    _settlement_players(room)                  — 结算顺序
    _settle_player(room, player, player_data)  — 单个玩家持久化，失败返回 False
    _format_result(player, room, settlement)   — 结算文案
    _build_settlement_messages(lobby, room, caller) — 结算通知
    _finalize_settlement(lobby, room, send_to_players) — 结算后收尾
    _match_disconnect(lobby, room, player_name) — 对局中断线处理

Bot 调度子类实现 `RoomBotScheduler._bot_move(engine, lobby, room, bot)`。
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import random
import threading
import time

from ..config import DEFAULT_LOCATION
from ..msg_types import (
    COMMANDS_UPDATE,
    GAME,
    GAME_INVITE,
    LOCATION_UPDATE,
    ROOM_UPDATE,
)
from .protocol import BaseGameEngine

logger = logging.getLogger(__name__)


class RoomGameEngine(BaseGameEngine):
    """房间制游戏引擎基座 — 子类只补玩法与文案。"""

    room_class: type = None
    min_players: int = 2
    bot_action: str = 'bot_turn'
    bot_delay_range: tuple[float, float] = (1.0, 2.5)

    _HOST_ONLY_COMMANDS = {'start', 'kick', 'bot', 'dissolve'}
    _NON_HOST_ONLY_COMMANDS = {'ready'}

    # ── 资源加载（游戏包 data/ 目录）──

    @staticmethod
    def _game_dir(module_file: str | None = None) -> str:
        return os.path.dirname(os.path.abspath(module_file or ''))

    @classmethod
    def load_data_text(cls, module_file: str, filename: str) -> str:
        path = os.path.join(cls._game_dir(module_file), 'data', filename)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return ''

    @classmethod
    def load_data_json(cls, module_file: str, filename: str) -> dict:
        path = os.path.join(cls._game_dir(module_file), 'data', filename)
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _game_info(self) -> dict:
        """游戏包 GAME_INFO（懒加载，供指令表与房间设置使用）。"""
        cached = getattr(self, '_game_info_cache', None)
        if cached is None:
            package = importlib.import_module(
                self.__class__.__module__.rsplit('.', 1)[0])
            cached = getattr(package, 'GAME_INFO', {})
            self._game_info_cache = cached
        return cached

    def __init__(self):
        self._init_rooms()

    # ── 文案（子类可覆盖以保持自己的措辞）──

    def _text_created(self, room_id: str) -> str:
        return f'创建了{self.display_name}房间 #{room_id}'

    def _text_start(self) -> str:
        return f'{self.display_name}开始！'

    def _text_left(self) -> str:
        return f'离开了{self.display_name}。'

    # ── Protocol ──

    def get_player_room(self, player_name: str):
        room_id = self._player_room.get(player_name)
        return self._rooms.get(room_id) if room_id else None

    def get_player_room_data(self, player_name: str) -> dict | None:
        room = self.get_player_room(player_name)
        return room.get_game_data(viewer=player_name) if room else None

    def _loc(self, room) -> str:
        return f'{self.game_key}#{room.room_id}'

    def get_commands(self, lobby, location, player_name, player_data):
        cmd_data = self._game_info().get('commands', {})
        key = f'{self.game_key}:{self._get_command_key(player_name)}'
        cmds = cmd_data.get(key, [])
        room = self.get_player_room(player_name)
        if room and room.host != player_name:
            return [c for c in cmds
                    if c.get('name') not in self._HOST_ONLY_COMMANDS]
        if room:
            cmds = [c for c in cmds
                    if c.get('name') not in self._NON_HOST_ONLY_COMMANDS]
            host = [c for c in cmds
                    if c.get('name') in self._HOST_ONLY_COMMANDS]
            rest = [c for c in cmds
                    if c.get('name') not in self._HOST_ONLY_COMMANDS]
            if host and rest:
                return host + [{'type': 'separator'}] + rest
        return list(cmds)

    def handle_disconnect(self, lobby, player_name):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            return self._match_disconnect(lobby, room, player_name)

        self._remove_player(player_name)
        if room and room.room_id in self._rooms:
            notify = self._notify_room_with_commands(
                lobby, room, f'{player_name} 断线了。')
            return [{'send_to_players': notify, 'refresh_room_list': True}]
        return []

    def handle_back(self, lobby, player_name, player_data):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            return self._select_menu('确认', [
                {'label': '确认放弃对局？', 'type': 'text'},
                {'type': 'separator'},
                {'label': '是', 'desc': '', 'command': '/forfeit'},
                {
                    'label': '否', 'desc': '',
                    'command': '', 'type': 'return',
                },
            ])
        if room and player_name in room._result_pending:
            room._result_pending.discard(player_name)
            td = room.get_table_data()
            loc = self._loc(room)
            return {
                'send_to_caller': [
                    {'type': ROOM_UPDATE, 'room_data': td},
                    {'type': LOCATION_UPDATE, 'location': loc},
                ],
                'refresh_commands': True,
            }
        if room:
            return self._cmd_leave(lobby, player_name, player_data, '')
        return self.handle_quit(lobby, player_name, player_data)

    def handle_quit(self, lobby, player_name, player_data):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            return self._select_menu('确认', [
                {'label': '确认放弃对局？', 'type': 'text'},
                {'type': 'separator'},
                {'label': '是', 'desc': '', 'command': '/forfeit'},
                {
                    'label': '否', 'desc': '',
                    'command': '', 'type': 'return',
                },
            ])
        self._remove_player(player_name)
        lobby.set_player_location(player_name, DEFAULT_LOCATION)
        result = {
            'action': 'location_update',
            'location': DEFAULT_LOCATION,
            'send_to_caller': [{'type': GAME, 'text': self._text_left()}],
            'refresh_commands': True,
            'refresh_room_list': True,
        }
        if room and room.room_id in self._rooms:
            result['send_to_players'] = self._notify_room_with_commands(
                lobby, room, f'{player_name} 离开了房间')
        return result

    def leave_room(self, player_name: str) -> None:
        self._remove_player(player_name)

    # ── 辅助 ──

    def _remove_player(self, player_name: str):
        room_id = self._player_room.pop(player_name, None)
        if room_id and room_id in self._rooms:
            room = self._rooms[room_id]
            room.players = [p for p in room.players if p != player_name]
            room.bots.discard(player_name)
            room.ready.discard(player_name)
            if not room.players or all(room.is_bot(p) for p in room.players):
                self._rooms.pop(room_id, None)
            elif room.host == player_name:
                for p in room.players:
                    if not room.is_bot(p):
                        room.host = p
                        room.ready.discard(p)
                        break

    def _cleanup_room(self, room):
        for p in room.players:
            self._player_room.pop(p, None)
        self._rooms.pop(room.room_id, None)

    def _notify_room(self, room, message, exclude=None, location=None):
        players = {}
        for p in room.players:
            if p == exclude or room.is_bot(p):
                continue
            rd = room.get_game_data(viewer=p)
            msgs = []
            if message:
                msgs.append({'type': GAME, 'text': message})
            msgs.append({'type': ROOM_UPDATE, 'room_data': rd})
            if location:
                msgs.append({'type': LOCATION_UPDATE, 'location': location})
            players[p] = msgs
        return players

    def _notify_room_with_commands(self, lobby, room, message, exclude=None):
        players = self._notify_room(room, message, exclude=exclude)
        for p, msgs in players.items():
            pd = lobby.online_players.get(p)
            if pd:
                loc = lobby.get_player_location(p)
                cmds = lobby.get_commands_for_location(loc, pd)
                msgs.append({'type': COMMANDS_UPDATE, 'commands': cmds})
        return players

    # ── 大厅 ──

    def _cmd_create(self, lobby, player_name, player_data, args):
        self._remove_player(player_name)
        room_id = self.gen_room_id()
        while room_id in self._rooms:
            room_id = self.gen_room_id()

        settings = self._parse_settings(args)
        room = self.room_class(room_id, [player_name], settings)

        if room.ranked:
            from ..systems.ranks import get_rank_info
            pdata = player_data.get(self.game_key, {})
            rank_id = pdata.get('rank', 1)
            info = get_rank_info(rank_id, self.game_key)
            room.rank_tier = info.get('tier', 1) if info else 1

        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        loc = self._loc(room)
        lobby.set_player_location(player_name, loc)
        return {
            'action': f'{self.game_key}_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': self._text_created(room_id)},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': loc},
            ],
            'refresh_commands': True,
            'refresh_room_list': True,
        }

    def _parse_settings(self, args: str) -> dict:
        if not args or not args.strip():
            return {}
        try:
            raw = json.loads(args.strip())
        except (json.JSONDecodeError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        schema = self._game_info().get('room_settings', [])
        valid_keys = {
            s['key']: {o['value'] for o in s['options']} for s in schema
        }
        result = {}
        for key, allowed in valid_keys.items():
            if key in raw and raw[key] in allowed:
                result[key] = raw[key]
        return result

    def _cmd_rooms(self, lobby, player_name, player_data, args):
        if not self._rooms:
            return self._msg(player_name, '暂无房间。')
        lines = ['当前房间:']
        for room in self._rooms.values():
            label = {
                'waiting': '等待中', 'playing': '进行中', 'finished': '已结束',
            }
            lines.append(
                f'  #{room.room_id}  {room.host}'
                f'  {len(room.players)}/{room.max_players}人'
                f'  {label.get(room.state, room.state)}'
            )
        return self._msg(player_name, '\n'.join(lines))

    def _cmd_accept(self, lobby, player_name, player_data, args):
        from ..config import INVITE_EXPIRE
        inv = self._invites.pop(player_name, None)
        if not inv or time.time() - inv['time'] > INVITE_EXPIRE:
            return self._msg(player_name, '没有待处理的邀请。')
        return self._do_join(lobby, player_name, player_data, inv['room_id'])

    def _cmd_join(self, lobby, player_name, player_data, args):
        room_id = args.strip()
        if not room_id:
            return self._msg(player_name, '请指定房间号。')
        return self._do_join(lobby, player_name, player_data, room_id)

    def _do_join(self, lobby, player_name, player_data, room_id):
        room = self._rooms.get(room_id)
        if not room or room.state != 'waiting':
            return self._msg(player_name, '房间已不可用。')
        if room.is_full():
            return self._msg(player_name, '房间已满。')

        if room.ranked:
            from ..systems.ranks import get_rank_info
            pdata = player_data.get(self.game_key, {})
            rank_id = pdata.get('rank', 1)
            info = get_rank_info(rank_id, self.game_key)
            player_tier = info.get('tier', 1) if info else 1
            if abs(player_tier - room.rank_tier) > 1:
                return self._msg(player_name, '你的段位与该房间不匹配。')

        self._remove_player(player_name)
        room.players.append(player_name)
        self._player_room[player_name] = room_id
        loc = self._loc(room)
        lobby.set_player_location(player_name, loc)

        td = room.get_table_data()
        notify = self._notify_room(room, f'{player_name} 加入了房间',
                                   exclude=player_name)
        return {
            'action': f'{self.game_key}_join',
            'send_to_caller': [
                {'type': GAME, 'text': f'加入了房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': td},
                {'type': LOCATION_UPDATE, 'location': loc},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
            'refresh_room_list': True,
        }

    # ── 房间 ──

    def _cmd_start(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        player_check = self._check_start_players(
            player_name, len(room.players), self.min_players,
            room.max_players, args)
        if player_check:
            return player_check
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已在进行中。')
        # 所有非房主、非 Bot 玩家都必须已准备
        not_ready = [p for p in room.players
                     if p != room.host and not room.is_bot(p)
                     and p not in room.ready]
        if not_ready:
            return self._msg(player_name,
                             f'还有玩家未准备：{", ".join(not_ready)}')
        room.ready.clear()

        first_msg = room.start()
        loc = self._loc(room)
        for p in room.players:
            if not room.is_bot(p):
                lobby.set_player_location(p, loc)

        game_text = self._text_start()
        if first_msg:
            game_text += f'\n{first_msg}'

        notify = self._notify_room(room, game_text,
                                   exclude=player_name, location=loc)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': f'{self.game_key}_start',
            'send_to_caller': [
                {'type': GAME, 'text': game_text},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': loc},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
            'refresh_room_list': True,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _cmd_ready(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'waiting':
            return self._msg(player_name, '当前不在等待中的房间。')
        if room.host == player_name:
            return self._msg(player_name, '房主无需准备。')
        if player_name in room.ready:
            room.ready.discard(player_name)
            text = '已取消准备。'
        else:
            room.ready.add(player_name)
            text = '已准备。'
        td = room.get_table_data()
        notify = {}
        for p in room.players:
            if p == player_name or room.is_bot(p):
                continue
            notify[p] = [{'type': ROOM_UPDATE, 'room_data': td}]
        return {
            'action': f'{self.game_key}_ready',
            'send_to_caller': [
                {'type': GAME, 'text': text},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
            'send_to_players': notify,
        }

    def _cmd_invite(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你不在房间中。')
        if room.is_full():
            return self._msg(player_name, '房间已满。')

        if not args or not args.startswith('@'):
            friends = player_data.get('friends', [])
            online = set(lobby.online_players)
            items = []
            for name in friends:
                if name not in online or self.get_player_room(name):
                    continue
                items.append({'label': name, 'command': f'/invite @{name}'})
            return self._select_menu(
                '邀请好友', items, '没有可邀请的在线好友。')

        from ..config import INVITE_EXPIRE
        target = args[1:].strip()
        friends = player_data.get('friends', [])
        if target not in friends:
            return self._msg(player_name, f'{target} 不是你的好友。')
        if target not in lobby.online_players:
            return self._msg(player_name, f'{target} 不在线。')
        self._invites[target] = {
            'from': player_name, 'room_id': room.room_id, 'time': time.time()}
        lobby._track_invite(player_name, player_data)
        if lobby.invite_callback:
            lobby.invite_callback(target, {
                'type': GAME_INVITE, 'from': player_name,
                'game': self.game_key, 'room_id': room.room_id,
                'expires_in': INVITE_EXPIRE,
            })
        return self._msg(player_name, f'已向 {target} 发送邀请。')

    def _cmd_kick(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '只有房主才能踢人。')
        others = [p for p in room.players if p != player_name]
        if not others:
            return self._msg(player_name, '房间里没有其他玩家。')

        if not args or not args.startswith('@'):
            items = [
                {'label': p, 'command': f'/kick @{p}'} for p in others
            ]
            return self._select_menu('踢出玩家', items)

        target = args[1:].strip()
        if target not in others:
            return self._msg(player_name, f'{target} 不在房间中。')
        room.players.remove(target)
        room.bots.discard(target)
        room.ready.discard(target)
        self._player_room.pop(target, None)
        lobby.set_player_location(target, DEFAULT_LOCATION)
        lobby_board = self._lobby_board()
        from ..lobby.help import get_help_welcome
        lobby_board['doc'] = (
            get_help_welcome(self.game_key) or self._HELP_TEXT)
        td = room.get_table_data()
        notify = self._notify_room(room, f'{target} 被踢出了房间',
                                   exclude=player_name)
        notify[target] = [
            {'type': GAME, 'text': '你被踢出了房间。'},
            {'type': ROOM_UPDATE, 'room_data': lobby_board},
            {'type': LOCATION_UPDATE, 'location': DEFAULT_LOCATION},
        ]
        target_pd = lobby.online_players.get(target)
        if target_pd:
            cmds = lobby.get_commands_for_location(
                DEFAULT_LOCATION, target_pd)
            notify[target].append(
                {'type': COMMANDS_UPDATE, 'commands': cmds})
        return {
            'action': f'{self.game_key}_kicked',
            'send_to_caller': [
                {'type': GAME, 'text': f'已踢出 {target}'},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    def _cmd_bot(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始。')
        if room.is_full():
            return self._msg(player_name, '房间已满。')

        ok, name = room.add_bot()
        if not ok:
            return self._msg(player_name, '无法添加机器人。')

        td = room.get_table_data()
        notify = self._notify_room(room, f'机器人 {name} 加入了房间',
                                   exclude=player_name)
        return {
            'action': f'{self.game_key}_bot_added',
            'send_to_caller': [
                {'type': GAME, 'text': f'已添加机器人: {name}'},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
            'send_to_players': notify,
        }

    def _cmd_dissolve(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '只有房主才能解散房间。')
        if room.state == 'playing':
            return self._msg(player_name, '游戏进行中，不能解散。')

        lobby_board = self._lobby_board()
        notify = {}
        for p in room.players:
            if p == player_name or room.is_bot(p):
                continue
            lobby.set_player_location(p, DEFAULT_LOCATION)
            pd = lobby.online_players.get(p)
            msgs = [
                {'type': GAME, 'text': '房主解散了房间。'},
                {'type': ROOM_UPDATE, 'room_data': lobby_board},
                {'type': LOCATION_UPDATE, 'location': DEFAULT_LOCATION},
            ]
            if pd:
                cmds = lobby.get_commands_for_location(
                    DEFAULT_LOCATION, pd)
                msgs.append({'type': COMMANDS_UPDATE, 'commands': cmds})
            notify[p] = msgs
        self._cleanup_room(room)
        lobby.set_player_location(player_name, DEFAULT_LOCATION)
        return {
            'action': f'{self.game_key}_dissolve',
            'send_to_caller': [
                {'type': GAME, 'text': '已解散房间。'},
                {'type': ROOM_UPDATE, 'room_data': lobby_board},
                {'type': LOCATION_UPDATE, 'location': DEFAULT_LOCATION},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
            'refresh_room_list': True,
        }

    def _cmd_leave(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            return self._msg(player_name, '游戏进行中，不能离开。')

        self._remove_player(player_name)
        lobby.set_player_location(player_name, DEFAULT_LOCATION)
        lobby_board = self._lobby_board()
        result = {
            'action': f'{self.game_key}_leave',
            'send_to_caller': [
                {'type': GAME, 'text': '离开了房间。'},
                {'type': ROOM_UPDATE, 'room_data': lobby_board},
                {'type': LOCATION_UPDATE, 'location': DEFAULT_LOCATION},
            ],
            'refresh_commands': True,
            'refresh_room_list': True,
        }
        if room and room.room_id in self._rooms:
            result['send_to_players'] = self._notify_room_with_commands(
                lobby, room, f'{player_name} 离开了房间')
        return result

    # ── 结算编排 ──

    @staticmethod
    def _unsettled_humans(room) -> list[str]:
        return [
            player for player in room.players
            if not room.is_bot(player)
            and player not in room._settled_players
        ]

    def _handle_game_over(self, lobby, room, caller, caller_data):
        if room.state != 'finished':
            return self._msg(caller, '游戏尚未结束。')

        # 先逐玩家提交完整结果。成功玩家立即记入房间阶段状态；后续玩家
        # 保存失败时，重试会跳过已提交玩家，而失败玩家的在线镜像未被修改。
        for player in self._settlement_players(room):
            if room.is_bot(player) or player in room._settled_players:
                continue
            player_data = lobby.online_players.get(player)
            if player == caller:
                player_data = caller_data
            if player_data is None:
                continue
            if not self._settle_player(room, player, player_data):
                return self._settlement_retry_result(room, caller)

        unsettled = self._unsettled_humans(room)
        if unsettled:
            logger.warning(
                "%s房间 %s 等待玩家数据后重试结算: %s",
                self.display_name, room.room_id, unsettled)
            return self._settlement_retry_result(room, caller)

        # 只有全部持久化阶段完成后才构造通知并切回等待状态。若此阶段异常，
        # 下一次调用仍会复用已记录的结算结果，不会再次发奖。
        caller_msgs, send_to_players, refresh_status = (
            self._build_settlement_messages(lobby, room, caller)
        )
        self._finalize_settlement(lobby, room, send_to_players)

        return {
            'action': f'{self.game_key}_game_over',
            'send_to_caller': caller_msgs or [],
            'send_to_players': send_to_players,
            'refresh_commands': True,
            'refresh_status': refresh_status,
        }

    # ── Bot ──

    def _maybe_schedule_bot(self, room) -> list[dict]:
        if room.state != 'playing':
            return []
        current = room.current_player()
        if current and room.is_bot(current):
            return [{
                'game_id': self.game_key,
                'action': self.bot_action,
                'room_id': room.room_id,
            }]
        return []

    # ── 玩法钩子（子类实现）──

    def _settlement_players(self, room) -> list[str]:
        return list(room.players)

    def _settle_player(self, room, player, player_data) -> bool:
        raise NotImplementedError

    def _format_result(self, player, room, settlement) -> str:
        raise NotImplementedError

    def _build_settlement_messages(self, lobby, room, caller):
        raise NotImplementedError

    def _finalize_settlement(self, lobby, room, send_to_players) -> None:
        raise NotImplementedError

    def _match_disconnect(self, lobby, room, player_name):
        raise NotImplementedError


class RoomBotScheduler:
    """房间制游戏的 Bot 调度器 — 负责延时执行、锁与结算重试。

    子类实现玩法回合（在持锁状态下调用）: `_do_turn(engine, lobby, room, bot)`。
    """

    def __init__(self, server, game_key: str, bot_action: str = 'bot_turn',
                 delay_range: tuple[float, float] = (1.0, 2.5)):
        self._server = server
        self._game_key = game_key
        self._bot_action = bot_action
        self._delay_range = delay_range

    def handle_schedule(self, task):
        action = task.get('action')
        room_id = task.get('room_id', '')
        if action == self._bot_action:
            delay = random.uniform(*self._delay_range)
            t = threading.Timer(delay, self._run_bot_turn, args=(room_id,))
            t.daemon = True
            t.start()
        elif action == 'settlement_retry':
            delay = task.get('delay', 1.0)
            generation = task.get('generation', -1)
            t = threading.Timer(
                delay, self._run_settlement_retry,
                args=(room_id, generation))
            t.daemon = True
            t.start()

    def _run_settlement_retry(self, room_id, generation):
        server = self._server
        lobby = server.lobby_engine
        with lobby._lock:
            engine = lobby.game_engines.get(self._game_key)
            if not engine:
                return
            result = engine._retry_settlement(lobby, room_id, generation)
            if result is not None:
                server.dispatch_game_result(result)

    def _run_bot_turn(self, room_id):
        server = self._server
        lobby = server.lobby_engine
        with lobby._lock:
            engine = lobby.game_engines.get(self._game_key)
            if not engine:
                return
            room = engine._rooms.get(room_id)
            if not room or room.state != 'playing':
                return

            bot_name = room.current_player()
            if not bot_name or not room.is_bot(bot_name):
                return

            self._bot_move(engine, lobby, room, bot_name)

    def _bot_move(self, engine, lobby, room, bot_name) -> None:
        """子类的 Bot 回合玩法（在持锁状态下调用）。"""
        raise NotImplementedError

    # ── Bot 回合通用动作 ──

    def _broadcast(self, engine, room, msg):
        server = self._server
        for p in room.players:
            if room.is_bot(p):
                continue
            board = room.get_game_data(viewer=p)
            msgs = []
            if msg:
                msgs.append({'type': GAME, 'text': msg})
            msgs.append({'type': ROOM_UPDATE, 'room_data': board})
            for m in msgs:
                server.send_to_player(p, m)

    def _handle_finish(self, engine, room):
        """Bot 触发的游戏结束"""
        server = self._server
        result = engine._handle_game_over(server.lobby_engine, room, '', {})
        server.dispatch_game_result(result)

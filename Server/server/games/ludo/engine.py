"""飞行棋引擎 — 2-4 人房间制

位置: lobby（大厅）/ ludo#房间号（房间内）
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading

from ...core.protocol import BaseGameEngine
from ...config import DEFAULT_LOCATION
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE, COMMANDS_UPDATE
from .room import LudoRoom, MIN_PLAYERS, MAX_PLAYERS
from .board import COLOR_NAMES

_dir = os.path.dirname(__file__)
_data_dir = os.path.join(_dir, 'data')
logger = logging.getLogger(__name__)


def _load_help() -> str:
    path = os.path.join(_data_dir, 'help.txt')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return ''


def _load_rewards() -> dict:
    path = os.path.join(_data_dir, 'rewards.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


class LudoEngine(BaseGameEngine):
    """飞行棋引擎"""

    game_key = 'ludo'
    display_name = '飞行棋'
    underfilled_start = 'forbid'
    _module_file = __file__
    _HELP_TEXT = _load_help()
    _REWARDS = _load_rewards()

    _GLOBAL_COMMANDS: dict[str, str] = {
        'create': '_cmd_create',
    }
    _COMMAND_MAP = {
        'lobby': {
            'rooms': '_cmd_rooms',
            'accept': '_cmd_accept',
            'join': '_cmd_join',
        },
        'room': {
            'start': '_cmd_start',
            'ready': '_cmd_ready',
            'invite': '_cmd_invite',
            'kick': '_cmd_kick',
            'bot': '_cmd_bot',
            'dissolve': '_cmd_dissolve',
        },
        'playing': {
            'roll': '_cmd_roll',
            'move': '_cmd_move',
            'forfeit': '_cmd_forfeit',
        },
    }

    def __init__(self):
        self._init_rooms()

    # ── Protocol ──

    def get_player_room(self, player_name: str) -> LudoRoom | None:
        room_id = self._player_room.get(player_name)
        return self._rooms.get(room_id) if room_id else None

    def get_player_room_data(self, player_name: str) -> dict | None:
        room = self.get_player_room(player_name)
        return room.get_game_data(viewer=player_name) if room else None

    def _loc(self, room: LudoRoom) -> str:
        return f'{self.game_key}#{room.room_id}'

    _HOST_ONLY_COMMANDS = {'start', 'kick', 'bot', 'dissolve'}
    _NON_HOST_ONLY_COMMANDS = {'ready'}

    def get_commands(self, lobby, location, player_name, player_data):
        from . import GAME_INFO
        cmd_data = GAME_INFO.get('commands', {})
        key = f'{self.game_key}:{self._get_command_key(player_name)}'
        cmds = cmd_data.get(key, [])
        room = self.get_player_room(player_name)
        if room and room.host != player_name:
            return [c for c in cmds if c.get('name') not in self._HOST_ONLY_COMMANDS]
        if room:
            cmds = [c for c in cmds if c.get('name') not in self._NON_HOST_ONLY_COMMANDS]
            host = [c for c in cmds if c.get('name') in self._HOST_ONLY_COMMANDS]
            rest = [c for c in cmds if c.get('name') not in self._HOST_ONLY_COMMANDS]
            if host and rest:
                return host + [{'type': 'separator'}] + rest
        return list(cmds)

    def handle_disconnect(self, lobby, player_name):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            # 有人离线，游戏强制退回等待界面
            room.reset_match()
            room.state = 'waiting'
            room.ready.clear()

            msg = f'{player_name} 断线了，游戏异常结束。'
            self._remove_player(player_name)

            td = room.get_table_data()
            send_to_players = {}
            for p in room.players:
                pd = lobby.online_players.get(p)
                if pd:
                    msgs = [
                        {'type': GAME, 'text': msg},
                        {'type': ROOM_UPDATE, 'room_data': td}
                    ]
                    cmds = lobby.get_commands_for_location(self._loc(room), pd)
                    msgs.append({'type': COMMANDS_UPDATE, 'commands': cmds})
                    send_to_players[p] = msgs

            return [{'send_to_players': send_to_players, 'refresh_room_list': True}]

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
            'send_to_caller': [{'type': GAME, 'text': '离开了飞行棋。'}],
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

    def _cleanup_room(self, room: LudoRoom):
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
        room = LudoRoom(room_id, [player_name], settings)

        if room.ranked:
            from ...systems.ranks import get_rank_info
            pdata = player_data.get('ludo', {})
            rank_id = pdata.get('rank', 1)
            info = get_rank_info(rank_id, 'ludo')
            room.rank_tier = info.get('tier', 1) if info else 1

        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        loc = self._loc(room)
        lobby.set_player_location(player_name, loc)
        return {
            'action': 'ludo_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': f'创建了飞行棋房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': loc},
            ],
            'refresh_commands': True,
            'refresh_room_list': True,
        }

    @staticmethod
    def _parse_settings(args: str) -> dict:
        if not args or not args.strip():
            return {}
        try:
            raw = json.loads(args.strip())
        except (json.JSONDecodeError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        from . import GAME_INFO
        schema = GAME_INFO.get('room_settings', [])
        valid_keys = {s['key']: {o['value'] for o in s['options']} for s in schema}
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
            label = {'waiting': '等待中', 'playing': '进行中', 'finished': '已结束'}
            lines.append(
                f'  #{room.room_id}  {room.host}'
                f'  {len(room.players)}/{room.max_players}人'
                f'  {label.get(room.state, room.state)}'
            )
        return self._msg(player_name, '\n'.join(lines))

    def _cmd_accept(self, lobby, player_name, player_data, args):
        import time
        from ...config import INVITE_EXPIRE
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
            from ...systems.ranks import get_rank_info
            pdata = player_data.get('ludo', {})
            rank_id = pdata.get('rank', 1)
            info = get_rank_info(rank_id, 'ludo')
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
            'action': 'ludo_join',
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
            player_name, len(room.players), MIN_PLAYERS,
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

        game_text = '飞行棋开始！'
        if first_msg:
            game_text += f'\n{first_msg}'

        notify = self._notify_room(room, game_text,
                                   exclude=player_name, location=loc)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'ludo_start',
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
            'action': 'ludo_ready',
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
            return self._select_menu('邀请好友', items, '没有可邀请的在线好友。')

        import time
        target = args[1:].strip()
        friends = player_data.get('friends', [])
        if target not in friends:
            return self._msg(player_name, f'{target} 不是你的好友。')
        if target not in lobby.online_players:
            return self._msg(player_name, f'{target} 不在线。')
        self._invites[target] = {
            'from': player_name, 'room_id': room.room_id, 'time': time.time()}
        lobby._track_invite(player_name, player_data)
        from ...msg_types import GAME_INVITE
        if lobby.invite_callback:
            from ...config import INVITE_EXPIRE
            lobby.invite_callback(target, {
                'type': GAME_INVITE, 'from': player_name,
                'game': 'ludo', 'room_id': room.room_id,
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
            items = [{'label': p, 'command': f'/kick @{p}'} for p in others]
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
        from ...lobby.help import get_help_welcome
        lobby_board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
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
            cmds = lobby.get_commands_for_location(DEFAULT_LOCATION, target_pd)
            notify[target].append({'type': COMMANDS_UPDATE, 'commands': cmds})
        return {
            'action': 'ludo_kicked',
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
            'action': 'ludo_bot_added',
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
                cmds = lobby.get_commands_for_location(DEFAULT_LOCATION, pd)
                msgs.append({'type': COMMANDS_UPDATE, 'commands': cmds})
            notify[p] = msgs
        self._cleanup_room(room)
        lobby.set_player_location(player_name, DEFAULT_LOCATION)
        return {
            'action': 'ludo_dissolve',
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
            'action': 'ludo_leave',
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

    # ── 游戏中 ──

    def _cmd_roll(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在游戏中。')

        ok, msg, dice = room.roll_dice(player_name)
        if not ok:
            return self._msg(player_name, msg)

        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)

        # 如果需要选棋子 → 弹出 select_menu
        if room.pending_move:
            color = room.player_colors[player_name]
            valid = room.board.get_valid_moves(color, dice)
            items = []
            for idx in valid:
                piece = room.board.pieces[color][idx]
                cn = COLOR_NAMES[color]
                if piece.state.value == 'airport':
                    desc = '起飞'
                elif piece.state.value == 'track':
                    desc = f'轨道@{piece.track_pos}'
                elif piece.state.value == 'runway':
                    desc = f'跑道@{piece.runway_pos}'
                else:
                    desc = ''
                items.append({
                    'label': f'{cn}{idx+1}号',
                    'desc': desc,
                    'command': f'/move {idx}',
                })
            notify = self._notify_room(room, msg, exclude=player_name)
            board = room.get_game_data(viewer=player_name)
            return {
                'action': 'ludo_roll',
                'send_to_caller': [
                    {'type': GAME, 'text': msg},
                    {'type': ROOM_UPDATE, 'room_data': board},
                    {'type': 'select_menu', 'title': '选择棋子',
                     'items': items},
                ],
                'send_to_players': notify,
            }

        notify = self._notify_room(room, msg, exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'ludo_roll',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': board},
                # 显式清空上一轮的 select_menu（防止起飞后选项残留）
                {'type': 'select_menu', 'title': '选择棋子', 'items': []},
            ],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _cmd_move(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在游戏中。')

        try:
            piece_idx = int(args.strip())
        except (ValueError, AttributeError):
            return self._msg(player_name, '无效的棋子编号。')

        ok, msg = room.move_piece(player_name, piece_idx)
        if not ok:
            return self._msg(player_name, msg)

        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)

        notify = self._notify_room(room, msg, exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'ludo_move',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': board},
            ],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _cmd_forfeit(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在游戏中。')

        # 玩家中途放弃，不踢出房间，而是整个游戏异常结束并重置为等待状态
        room.reset_match()
        room.state = 'waiting'

        msg = f'{player_name} 放弃了对局，游戏结束。'
        notify = self._notify_room(room, msg, exclude=player_name)

        td = room.get_table_data()

        for p, msgs in notify.items():
            pd = lobby.online_players.get(p)
            if pd:
                cmds = lobby.get_commands_for_location(self._loc(room), pd)
                msgs.append({'type': COMMANDS_UPDATE, 'commands': cmds})

        pd_caller = lobby.online_players.get(player_name)
        cmds_caller = lobby.get_commands_for_location(self._loc(room), pd_caller) if pd_caller else []

        return {
            'action': 'ludo_forfeit',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': td},
                {'type': COMMANDS_UPDATE, 'commands': cmds_caller},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
            'refresh_room_list': True,
        }

    # ── 结算 ──

    def _rank_settlement(self, rank_index: int, player_count: int):
        if rank_index == 0:
            outcome = 'win'
        elif rank_index == player_count - 1:
            outcome = 'loss'
        else:
            outcome = 'draw'
        exp, gold = self._REWARDS.get(outcome, [100, 10])
        return outcome, exp, gold

    def _settle_ranked_player(
        self,
        room,
        player: str,
        player_data: dict,
        rank_index: int,
        player_count: int,
        has_bots: bool,
    ) -> bool:
        from copy import deepcopy
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        outcome, exp, gold = self._rank_settlement(
            rank_index, player_count,
        )
        working = deepcopy(player_data)
        self._apply_game_result(working, outcome)
        rank_change = self._update_player_rank(
            working, outcome, has_bots,
        )
        if has_bots and gold > 0:
            gold = int(
                exp * self._REWARDS.get('gold_ratio_bot', 0.15)
            )
        working['exp'] = working.get('exp', 0) + exp
        check_level_up(working)
        working['gold'] = max(0, working.get('gold', 0) + gold)

        try:
            PlayerManager.save_player_data(player, working)
        except OSError:
            logger.exception(
                "飞行棋房间 %s 的玩家 %s 结算保存失败，等待重试",
                room.room_id, player)
            return False

        room._settlement_results[player] = {
            'rank_index': rank_index,
            'exp': exp,
            'gold': gold,
            'rank_change': rank_change,
        }
        room._settled_players.add(player)
        working.pop('password_hash', None)
        player_data.clear()
        player_data.update(working)
        return True

    @staticmethod
    def _unsettled_humans(room) -> list[str]:
        return [
            player for player in room.players
            if not room.is_bot(player)
            and player not in room._settled_players
        ]

    def _build_settlement_messages(self, lobby, room, caller):
        send_to_players = {}
        refresh_status = []
        caller_messages = None
        location = self._loc(room)
        for player in room.rankings:
            settlement = room._settlement_results.get(player)
            if settlement is None:
                continue
            refresh_status.append(player)
            lobby.set_player_location(player, location)
            result_text = self._format_result(
                player,
                room,
                settlement['rank_index'],
                settlement['exp'],
                settlement['gold'],
                settlement['rank_change'],
            )
            messages = [
                {'type': GAME, 'text': result_text},
                {
                    'type': ROOM_UPDATE,
                    'room_data': room.get_game_data(viewer=player),
                },
                {'type': LOCATION_UPDATE, 'location': location},
            ]
            if player == caller:
                caller_messages = messages
            else:
                send_to_players[player] = messages
        return caller_messages, send_to_players, refresh_status

    @staticmethod
    def _finish_settlement(room) -> None:
        room.state = 'waiting'
        room._settlement_retry_scheduled = False
        room.board = None
        room._result_pending = {
            player for player in room.players if not room.is_bot(player)
        }

    @staticmethod
    def _append_settlement_commands(lobby, send_to_players: dict) -> None:
        for player, messages in send_to_players.items():
            player_data = lobby.online_players.get(player)
            if not player_data:
                continue
            location = lobby.get_player_location(player)
            commands = lobby.get_commands_for_location(
                location, player_data,
            )
            messages.append({
                'type': COMMANDS_UPDATE,
                'commands': commands,
            })

    def _handle_game_over(self, lobby, room, caller, caller_data):
        if room.state != 'finished':
            return self._msg(caller, '游戏尚未结束。')

        has_bots = bool(room.bots)
        n_players = len(room.players)

        for rank_index, player in enumerate(room.rankings):
            if room.is_bot(player) or player in room._settled_players:
                continue
            player_data = (
                caller_data
                if player == caller
                else lobby.online_players.get(player)
            )
            if player_data is None:
                continue
            if not self._settle_ranked_player(
                room,
                player,
                player_data,
                rank_index,
                n_players,
                has_bots,
            ):
                return self._settlement_retry_result(room, caller)

        unsettled = self._unsettled_humans(room)
        if unsettled:
            logger.warning(
                "飞行棋房间 %s 等待玩家数据后重试结算: %s",
                room.room_id, unsettled)
            return self._settlement_retry_result(room, caller)

        caller_msgs, send_to_players, refresh_status = (
            self._build_settlement_messages(lobby, room, caller)
        )
        self._finish_settlement(room)
        self._append_settlement_commands(lobby, send_to_players)

        return {
            'action': 'ludo_game_over',
            'send_to_caller': caller_msgs or [],
            'send_to_players': send_to_players,
            'refresh_commands': True,
            'refresh_status': refresh_status,
        }

    def _broadcast_game_over(self, lobby, room, disconnected):
        """断线时触发的游戏结束"""
        send_to_players = {}
        for p in room.players:
            if p == disconnected or room.is_bot(p):
                continue
            pd = lobby.online_players.get(p)
            if not pd:
                continue
            board = room.get_game_data(viewer=p)
            board['message'] = f'{disconnected} 断线了，游戏结束。'
            send_to_players[p] = [
                {'type': GAME, 'text': f'{disconnected} 断线了。'},
                {'type': ROOM_UPDATE, 'room_data': board},
            ]
        self._cleanup_room(room)
        return [{'send_to_players': send_to_players, 'refresh_room_list': True}]

    def _format_result(self, player, room, rank_idx, exp, gold, rc):
        lines = []
        ordinals = ['第一名', '第二名', '第三名', '第四名']
        lines.append(f'{ordinals[rank_idx]}！')
        gold_sign = '+' if gold >= 0 else ''
        lines.append(f'经验 +{exp}  金币 {gold_sign}{gold}')
        if rc and rc.get('delta', 0) != 0:
            d = rc['delta']
            sign = '+' if d > 0 else ''
            part = f'段位 {sign}{d}'
            if rc.get('promoted'):
                part += f' 升段→{rc["new_rank_name"]}'
            elif rc.get('demoted'):
                part += f' 降段→{rc["new_rank_name"]}'
            lines.append(part)
        return '\n'.join(lines)

    # ── Bot ──

    def _maybe_schedule_bot(self, room) -> list[dict]:
        if room.state != 'playing':
            return []
        current = room.current_player()
        if current and room.is_bot(current):
            return [{
                'game_id': 'ludo',
                'action': 'bot_turn',
                'room_id': room.room_id,
            }]
        return []


class LudoBotScheduler:
    """飞行棋 Bot 调度器"""

    def __init__(self, server):
        self._server = server

    def handle_schedule(self, task):
        action = task.get('action')
        room_id = task.get('room_id', '')
        if action == 'bot_turn':
            delay = random.uniform(1.0, 2.5)
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
            engine = lobby.game_engines.get('ludo')
            if not engine:
                return
            result = engine._retry_settlement(lobby, room_id, generation)
            if result is not None:
                server.dispatch_game_result(result)

    def _run_bot_turn(self, room_id):
        server = self._server
        lobby = server.lobby_engine
        with lobby._lock:
            engine = lobby.game_engines.get('ludo')
            if not engine:
                return
            room = engine._rooms.get(room_id)
            if not room or room.state != 'playing':
                return

            bot_name = room.current_player()
            if not bot_name or not room.is_bot(bot_name):
                return

            self._do_turn(engine, lobby, room, bot_name)

    def _do_turn(self, engine, lobby, room, bot_name):
        """Bot 回合: 掷骰子 → 选棋子"""
        ok, msg, dice = room.roll_dice(bot_name)
        if not ok:
            return

        # 三连6或无棋可走时已自动处理
        if not room.pending_move:
            self._broadcast(engine, room, msg)
            if room.state == 'finished':
                self._handle_finish(engine, room)
            elif dice == 6 and room.is_bot(room.current_player()):
                # 掷6再来一次
                for t in engine._maybe_schedule_bot(room):
                    self.handle_schedule(t)
            else:
                for t in engine._maybe_schedule_bot(room):
                    self.handle_schedule(t)
            return

        # 需要选棋子 — AI 策略
        color = room.player_colors[bot_name]
        valid = room.board.get_valid_moves(color, dice)
        piece_idx = self._pick_best_move(room, color, valid, dice)
        ok2, msg2 = room.move_piece(bot_name, piece_idx)
        full_msg = f'{msg}\n{msg2}' if msg2 else msg

        self._broadcast(engine, room, full_msg)
        if room.state == 'finished':
            self._handle_finish(engine, room)
        else:
            for t in engine._maybe_schedule_bot(room):
                self.handle_schedule(t)

    def _pick_best_move(self, room, color, valid, dice):
        """Bot AI 选棋策略: 吃子 > 起飞 > 最远棋子"""
        from .board import (PieceState, _COLOR_CONFIG, _wrap,
                            TRACK_LEN, RUNWAY_LEN)

        conf = _COLOR_CONFIG[color]
        board = room.board
        best_idx = valid[0]
        best_score = -1

        for idx in valid:
            piece = board.pieces[color][idx]
            score = 0

            if piece.state == PieceState.AIRPORT:
                # 起飞 — 中等优先
                score = 50
                # 检查起飞点是否有敌方棋子可吃
                start_pos = conf['start']
                enemies = [p for p in board.pieces_at_track(start_pos)
                           if p.color != color]
                if enemies:
                    score = 100
            elif piece.state == PieceState.TRACK:
                target = _wrap(piece.track_pos + dice)
                # 能吃子 → 最高优先
                enemies = [p for p in board.pieces_at_track(target)
                           if p.color != color]
                if enemies:
                    score = 100
                else:
                    # 距离终点越近越好
                    dist = (conf['turn_in'] - piece.track_pos) % TRACK_LEN
                    score = TRACK_LEN - dist
            elif piece.state == PieceState.RUNWAY:
                target_rw = piece.runway_pos + dice
                if target_rw == RUNWAY_LEN:
                    score = 200  # 精确到达终点
                else:
                    score = 30

            if score > best_score:
                best_score = score
                best_idx = idx

        return best_idx

    def _broadcast(self, engine, room, msg):
        server = self._server
        for p in room.players:
            if not room.is_bot(p):
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
        result = engine._handle_game_over(
            server.lobby_engine, room, '', {})
        server.dispatch_game_result(result)


def create_bot_scheduler(server):
    return LudoBotScheduler(server)

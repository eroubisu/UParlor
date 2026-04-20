"""UNO Flip 引擎 — 2-10 人房间制

位置: lobby（大厅）/ uno#房间号（房间内）
"""

from __future__ import annotations

import json
import os
import random
import threading

from ...core.protocol import BaseGameEngine
from ...config import DEFAULT_LOCATION
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE, COMMANDS_UPDATE
from .room import UnoRoom, MIN_PLAYERS, MAX_PLAYERS
from .cards import LIGHT_COLORS, DARK_COLORS, COLOR_NAMES, VALUE_LABELS

_dir = os.path.dirname(__file__)
_data_dir = os.path.join(_dir, 'data')


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


class UnoEngine(BaseGameEngine):
    """UNO Flip 引擎"""

    game_key = 'uno'
    display_name = 'UNO Flip'
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
            'invite': '_cmd_invite',
            'kick': '_cmd_kick',
            'bot': '_cmd_bot',
            'dissolve': '_cmd_dissolve',
        },
        'playing': {
            'play': '_cmd_play',
            'draw': '_cmd_draw',
            'uno': '_cmd_uno',
            'pass': '_cmd_pass',
            'challenge': '_cmd_challenge',
            'forfeit': '_cmd_forfeit',
        },
    }

    def __init__(self):
        self._init_rooms()

    # ── Protocol ──

    def get_player_room(self, player_name: str) -> UnoRoom | None:
        room_id = self._player_room.get(player_name)
        return self._rooms.get(room_id) if room_id else None

    def get_player_room_data(self, player_name: str) -> dict | None:
        room = self.get_player_room(player_name)
        return room.get_game_data(viewer=player_name) if room else None

    def _loc(self, room: UnoRoom) -> str:
        """返回游戏内位置: uno#room_id"""
        return f'{self.game_key}#{room.room_id}'

    _HOST_ONLY_COMMANDS = {'start', 'kick', 'bot', 'dissolve'}

    def get_commands(self, lobby, location, player_name, player_data):
        """根据房间状态返回指令列表，非房主过滤房主专属指令。"""
        import copy
        from . import GAME_INFO
        cmd_data = GAME_INFO.get('commands', {})
        key = f'{self.game_key}:{self._get_command_key(player_name)}'
        cmds = copy.deepcopy(cmd_data.get(key, []))
        room = self.get_player_room(player_name)
        if room and room.host != player_name:
            cmds = [c for c in cmds if c.get('name') not in self._HOST_ONLY_COMMANDS]
        elif room:
            host = [c for c in cmds if c.get('name') in self._HOST_ONLY_COMMANDS]
            rest = [c for c in cmds if c.get('name') not in self._HOST_ONLY_COMMANDS]
            if host and rest:
                cmds = host + [{'type': 'separator'}] + rest
        return cmds

    def handle_disconnect(self, lobby, player_name):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            room.state = 'finished'
            room.winner = ''
            send_to_players = {}
            for p in room.players:
                if p == player_name or room.is_bot(p):
                    continue
                pd = lobby.online_players.get(p)
                if not pd:
                    continue
                loc = self._loc(room)
                board = room.get_game_data(viewer=p)
                board['message'] = f'{player_name} 断线了，游戏结束。'
                send_to_players[p] = [
                    {'type': GAME, 'text': f'{player_name} 断线了。'},
                    {'type': ROOM_UPDATE, 'room_data': board},
                    {'type': LOCATION_UPDATE, 'location': loc},
                ]
            self._cleanup_room(room)
            return [{'send_to_players': send_to_players, 'refresh_room_list': True}]
        self._remove_player(player_name)
        # 非 playing 状态下通知房间其他玩家
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
                {'label': '否', 'desc': '', 'command': ''},
            ])
        if room and player_name in room._result_pending:
            # 刚结束 → 回到等待室
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
                {'label': '否', 'desc': '', 'command': ''},
            ])
        self._remove_player(player_name)
        lobby.set_player_location(player_name, DEFAULT_LOCATION)
        result = {
            'action': 'location_update',
            'location': DEFAULT_LOCATION,
            'send_to_caller': [{'type': GAME, 'text': '离开了 UNO Flip。'}],
            'refresh_commands': True,
            'refresh_room_list': True,
        }
        if room and room.room_id in self._rooms:
            result['send_to_players'] = self._notify_room_with_commands(
                lobby, room, f'{player_name} 离开了房间')
        return result

    def leave_room(self, player_name: str) -> None:
        """离开房间"""
        self._remove_player(player_name)

    # ── 辅助 ──

    def _remove_player(self, player_name: str):
        room_id = self._player_room.pop(player_name, None)
        if room_id and room_id in self._rooms:
            room = self._rooms[room_id]
            room.players = [p for p in room.players if p != player_name]
            room.bots.discard(player_name)
            if not room.players or all(room.is_bot(p) for p in room.players):
                self._rooms.pop(room_id, None)
            elif room.host == player_name:
                for p in room.players:
                    if not room.is_bot(p):
                        room.host = p
                        break

    def _cleanup_room(self, room: UnoRoom):
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
        """通知房间其他玩家（含 COMMANDS_UPDATE），用于房主变更等场景"""
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

        # 解析设置
        settings = self._parse_settings(args)
        room = UnoRoom(room_id, [player_name], settings)

        # 竞技模式：记录房主段位阶梯
        if room.ranked:
            from ...systems.ranks import get_rank_info
            pdata = player_data.get('uno', {})
            rank_id = pdata.get('rank', 1)
            info = get_rank_info(rank_id, 'uno')
            room.rank_tier = info.get('tier', 1) if info else 1

        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        loc = self._loc(room)
        lobby.set_player_location(player_name, loc)
        return {
            'action': 'uno_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': f'创建了 UNO Flip 房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': loc},
            ],
            'refresh_commands': True,
            'refresh_room_list': True,
        }

    @staticmethod
    def _parse_settings(args: str) -> dict:
        """从 /create 参数解析房间设置，返回验证后的 dict"""
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
        """共享加入房间逻辑"""
        room = self._rooms.get(room_id)
        if not room or room.state != 'waiting':
            return self._msg(player_name, '房间已不可用。')
        if room.is_full():
            return self._msg(player_name, '房间已满。')

        # 竞技模式段位限制（±1 阶梯）
        if room.ranked:
            from ...systems.ranks import get_rank_info
            pdata = player_data.get('uno', {})
            rank_id = pdata.get('rank', 1)
            info = get_rank_info(rank_id, 'uno')
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
            'action': 'uno_join',
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
        if len(room.players) < MIN_PLAYERS:
            return self._msg(player_name, f'需要至少 {MIN_PLAYERS} 名玩家。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已在进行中。')

        first_msg = room.start()
        loc = self._loc(room)
        for p in room.players:
            if not room.is_bot(p):
                lobby.set_player_location(p, loc)

        game_text = 'UNO Flip 开始！'
        if first_msg:
            game_text += f'\n{first_msg}'

        notify = self._notify_room(room, game_text,
                                   exclude=player_name,
                                   location=loc)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'uno_start',
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
                'game': 'uno', 'room_id': room.room_id,
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
            'action': 'uno_kicked',
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

        empty = MAX_PLAYERS - len(room.players)
        if empty <= 0:
            return self._msg(player_name, '房间已满。')

        added = []
        ok, name = room.add_bot()
        if ok:
            added.append(name)

        if not added:
            return self._msg(player_name, '无法添加机器人。')

        names = ', '.join(added)
        td = room.get_table_data()
        notify = self._notify_room(room, f'机器人 {names} 加入了房间',
                                   exclude=player_name)
        return {
            'action': 'uno_bot_added',
            'send_to_caller': [
                {'type': GAME, 'text': f'已添加机器人: {names}'},
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
            'action': 'uno_dissolve',
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
            'action': 'uno_leave',
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

    # ── 游戏中: 出牌 ──

    def _cmd_play(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在游戏中。')
        if player_name != room.current_player():
            return self._msg(player_name, '不是你的回合。')

        # 无参: 弹出 select_menu
        if not args:
            return self._play_select_menu(room, player_name)

        # 解析: /play <card_idx> [color]
        parts = args.strip().split()
        try:
            card_idx = int(parts[0])
        except ValueError:
            return self._msg(player_name, '无效的牌序号。')

        chosen_color = parts[1] if len(parts) > 1 else None

        ok, msg = room.play_card(player_name, card_idx, chosen_color)

        if not ok:
            if msg == 'need_color':
                # 需要选颜色 → 弹二级菜单
                return self._color_select_menu(card_idx, room.side)
            return self._msg(player_name, msg)

        # 出牌成功
        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)

        notify = self._notify_room(room, msg, exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'uno_play',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': board},
            ],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _play_select_menu(self, room: UnoRoom, player_name: str):
        """构建出牌选择菜单"""
        hand = room.hands.get(player_name, [])
        playable = room.get_playable_indices(player_name)

        items = []
        for i in playable:
            card = hand[i]
            items.append({
                'label': card.label,
                'desc': card.desc,
                'command': f'/play {i}',
            })

        # 没有可出的牌或有 pending_draw 时，显示摸牌选项
        if not playable or room.pending_draw > 0 or room.draw_until_color:
            draw_desc = f'摸 {room.pending_draw} 张' if room.pending_draw > 0 else '摸牌'
            if room.draw_until_color:
                c = COLOR_NAMES.get(room.draw_until_color, '?')
                draw_desc = f'摸到{c}色为止'
            items.append({
                'label': '摸牌',
                'desc': draw_desc,
                'command': '/draw',
            })

        # 挑战选项
        if room.challengeable:
            items.append({
                'label': '挑战',
                'desc': '质疑上家出牌合法性',
                'command': '/challenge',
            })

        return self._select_menu('出牌', items, '没有可出的牌，请摸牌。')

    def _color_select_menu(self, card_idx: int, side: str):
        """Wild 牌选颜色子菜单"""
        colors = LIGHT_COLORS if side == 'light' else DARK_COLORS
        items = []
        for color in colors:
            items.append({
                'label': COLOR_NAMES[color],
                'desc': color,
                'command': f'/play {card_idx} {color}',
            })
        return self._select_menu('选择颜色', items)

    # ── 游戏中: 摸牌 ──

    def _cmd_draw(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在游戏中。')

        ok, msg, drawn = room.draw_cards(player_name)
        if not ok:
            return self._msg(player_name, msg)

        notify = self._notify_room(room, msg, exclude=player_name)
        # 摸到可出的牌时 draw_play 由 room 数据携带
        board = room.get_game_data(viewer=player_name)

        return {
            'action': 'uno_draw',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': board},
            ],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    # ── 游戏中: 跳过（摸牌后不出）──

    def _cmd_pass(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在游戏中。')

        ok, msg = room.pass_turn(player_name)
        if not ok:
            return self._msg(player_name, msg)

        notify = self._notify_room(room, msg, exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'uno_pass',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': board},
            ],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    # ── 游戏中: UNO 喊牌 ──

    def _cmd_uno(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在游戏中。')

        ok, msg = room.call_uno(player_name)
        if not ok:
            return self._msg(player_name, msg)

        notify = self._notify_room(room, msg, exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'uno_call',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': board},
            ],
            'send_to_players': notify,
        }

    # ── 游戏中: 挑战 ──

    def _cmd_challenge(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在游戏中。')

        ok, msg = room.challenge(player_name)
        if not ok:
            return self._msg(player_name, msg)

        notify = self._notify_room(room, msg, exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'uno_challenge',
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

        msg = f'{player_name} 放弃了游戏。'
        room.state = 'waiting'
        room.hands.clear()

        loc = self._loc(room)
        td = room.get_table_data()
        td['message'] = msg

        notify = {}
        for p in room.players:
            if p == player_name or room.is_bot(p):
                continue
            notify[p] = [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': td},
                {'type': LOCATION_UPDATE, 'location': loc},
            ]

        return {
            'action': 'uno_forfeit',
            'send_to_caller': [
                {'type': GAME, 'text': '你放弃了游戏。'},
                {'type': ROOM_UPDATE, 'room_data': td},
                {'type': LOCATION_UPDATE, 'location': loc},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    # ── 结算 ──

    def _handle_game_over(self, lobby, room, caller, caller_data):
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        send_to_players = {}
        refresh_status = []
        caller_msgs = None
        has_bots = bool(room.bots)
        rank_changes = {}

        for p in room.players:
            if room.is_bot(p):
                continue
            pd = caller_data if p == caller else lobby.online_players.get(p)
            if pd is None:
                continue

            outcome = 'win' if p == room.winner else 'loss'
            if outcome == 'win':
                exp, gold = self._REWARDS['win']
                self.report_game_result(lobby, p, pd, 'win')
                rc = self._update_player_rank(pd, 'win', has_bots)
            else:
                exp, gold = self._REWARDS['loss']
                self.report_game_result(lobby, p, pd, 'loss')
                rc = self._update_player_rank(pd, 'loss', has_bots)
            rank_changes[p] = rc

            if has_bots:
                gold = int(exp * self._REWARDS.get('gold_ratio_bot', 0.15))

            pd['exp'] = pd.get('exp', 0) + exp
            check_level_up(pd)
            pd['gold'] = max(0, pd.get('gold', 0) + gold)
            PlayerManager.save_player_data(p, pd)
            refresh_status.append(p)

            lobby.set_player_location(p, self._loc(room))
            board = room.get_game_data(viewer=p)
            board['rank_changes'] = rank_changes
            result_text = self._format_result(p, room, exp, gold, rank_changes.get(p))
            msgs = [
                {'type': GAME, 'text': result_text},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': self._loc(room)},
            ]
            if p == caller:
                caller_msgs = msgs
            else:
                send_to_players[p] = msgs

        room.state = 'waiting'
        room.hands.clear()
        room._result_pending = {p for p in room.players if not room.is_bot(p)}

        # 为所有非 caller 玩家追加 commands_update（caller 由 refresh_commands 处理）
        for p, msgs in send_to_players.items():
            pd = lobby.online_players.get(p)
            if pd:
                loc = lobby.get_player_location(p)
                cmds = lobby.get_commands_for_location(loc, pd)
                msgs.append({'type': COMMANDS_UPDATE, 'commands': cmds})

        return {
            'action': 'uno_game_over',
            'send_to_caller': caller_msgs or [],
            'send_to_players': send_to_players,
            'refresh_commands': True,
            'refresh_status': refresh_status,
        }

    def _format_result(self, player, room, exp, gold, rc):
        lines = []
        if room.winner:
            lines.append(f'★ {room.winner} 获胜！')
        if room.scores:
            total = sum(v for k, v in room.scores.items() if v > 0)
            if total:
                lines.append(f'赢家得分: {total}')
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
                'game_id': 'uno',
                'action': 'bot_play',
                'room_id': room.room_id,
            }]
        return []


class UnoBotScheduler:
    """UNO Flip Bot 调度器"""

    def __init__(self, server):
        self._server = server

    def handle_schedule(self, task):
        action = task.get('action')
        room_id = task.get('room_id', '')
        if action == 'bot_play':
            delay = random.uniform(1.0, 3.0)
            t = threading.Timer(delay, self._run_bot_turn, args=(room_id,))
            t.daemon = True
            t.start()

    def _run_bot_turn(self, room_id):
        server = self._server
        lobby = server.lobby_engine
        with lobby._lock:
            engine = lobby.game_engines.get('uno')
            if not engine:
                return
            room = engine._rooms.get(room_id)
            if not room or room.state != 'playing':
                return

            bot_name = room.current_player()
            if not bot_name or not room.is_bot(bot_name):
                return

            self._do_play(engine, lobby, room, bot_name)

    def _do_play(self, engine, lobby, room, bot_name):
        """Bot 出牌策略: 简单 AI"""
        hand = room.hands.get(bot_name, [])
        if not hand:
            return

        # 摸牌后可出状态：直接出牌
        if room.draw_play_card is not None:
            idx = room.draw_play_card
            card = hand[idx]
            chosen_color = None
            if card.is_wild:
                chosen_color = self._pick_best_color(hand, room.side)
            ok, msg = room.play_card(bot_name, idx, chosen_color)
            if not ok:
                # 出牌失败则跳过
                ok, msg = room.pass_turn(bot_name)
            if len(room.hands.get(bot_name, [])) == 1:
                room.call_uno(bot_name)
            self._broadcast(engine, room, msg)
            return

        # 如果需要摸牌（pending_draw 或 draw_until_color）
        if room.draw_until_color:
            ok, msg, _ = room.draw_cards(bot_name)
            self._broadcast(engine, room, msg)
            return

        playable = room.get_playable_indices(bot_name)

        # 有 pending_draw 且没有可叠加的牌 → 摸牌
        if room.pending_draw > 0 and not playable:
            ok, msg, _ = room.draw_cards(bot_name)
            self._broadcast(engine, room, msg)
            return

        if not playable:
            # 没有可出的牌 → 摸牌
            ok, msg, _ = room.draw_cards(bot_name)
            self._broadcast(engine, room, msg)
            return

        # 选牌策略: 优先出功能牌，其次数字大的
        best_idx = playable[0]
        best_priority = -1
        for idx in playable:
            card = hand[idx]
            if card.value in ('wild_draw2', 'wild_draw_color'):
                p = 10
            elif card.value in ('draw1', 'draw5'):
                p = 8
            elif card.value in ('skip', 'skip_all', 'reverse'):
                p = 6
            elif card.value == 'flip':
                p = 4
            elif card.is_wild:
                p = 2  # 普通 Wild 留到后面
            else:
                p = 1
            if p > best_priority:
                best_priority = p
                best_idx = idx

        card = hand[best_idx]

        # Wild 牌需要选颜色: 选手牌中最多的颜色
        chosen_color = None
        if card.is_wild:
            chosen_color = self._pick_best_color(hand, room.side)

        ok, msg = room.play_card(bot_name, best_idx, chosen_color)
        if not ok:
            # 出牌失败 → 摸牌
            ok, msg, _ = room.draw_cards(bot_name)

        # 剩 1 张时喊 UNO
        if len(room.hands.get(bot_name, [])) == 1:
            room.call_uno(bot_name)

        self._broadcast(engine, room, msg)

    def _pick_best_color(self, hand: list, side: str) -> str:
        """选手牌中最多的颜色"""
        colors = LIGHT_COLORS if side == 'light' else DARK_COLORS
        counts = {c: 0 for c in colors}
        for card in hand:
            if card.color in counts:
                counts[card.color] += 1
        return max(counts, key=counts.get)

    def _broadcast(self, engine, room, msg):
        server = self._server
        with server.lock:
            for p in room.players:
                if not room.is_bot(p):
                    board = room.get_game_data(viewer=p)
                    msgs = []
                    if msg:
                        msgs.append({'type': GAME, 'text': msg})
                    msgs.append({'type': ROOM_UPDATE, 'room_data': board})
                    for m in msgs:
                        server.send_to_player(p, m)

            if room.state == 'finished':
                for p in room.players:
                    if not room.is_bot(p):
                        pd = server._get_player_data(p)
                        if pd:
                            from ...core.result_dispatcher import dispatch_game_result
                            result = engine._handle_game_over(
                                server.lobby_engine, room, p, pd)
                            dispatch_game_result(
                                server, result, caller_name=p, caller_data=pd)
                            break
            else:
                for t in engine._maybe_schedule_bot(room):
                    self.handle_schedule(t)


def create_bot_scheduler(server):
    return UnoBotScheduler(server)

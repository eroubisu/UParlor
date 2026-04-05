"""日本麻将游戏引擎 — 指令路由 + 机器人 AI

房间状态管理由 room.py (MahjongRoom) 负责。
牌编码/显示由 tiles.py 负责。
本模块仅负责: 指令分发、消息组装、机器人决策。
"""

from __future__ import annotations

import json
import os
import random
import time

from mahjong.shanten import Shanten

from ...core.protocol import BaseGameEngine
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE

from .room import MahjongRoom, MAX_PLAYERS
from .tiles import tile_to_str, tile_to_chinese, hand_to_34, POSITION_NAMES
from .bot import MahjongBot

_dir = os.path.dirname(__file__)
_data_dir = os.path.join(_dir, 'data')
_shanten = Shanten()
_bot_ai = MahjongBot()


def _load_help() -> str:
    path = os.path.join(_data_dir, 'help.txt')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _load_rewards() -> dict:
    path = os.path.join(_data_dir, 'rewards.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


class MahjongEngine(BaseGameEngine):
    """麻将游戏引擎 — 房间制

    所有游戏反馈通过 ROOM_UPDATE 传递到客户端游戏面板。
    """

    game_key = 'mahjong'
    display_name = '麻将'
    _HELP_TEXT = _load_help()
    _REWARDS = _load_rewards()

    _GLOBAL_COMMANDS: dict[str, str] = {}
    _COMMAND_MAP = {
        'lobby': {
            'create': '_cmd_create',
            'rooms': '_cmd_rooms',
            'join': '_cmd_join',
            'accept': '_cmd_accept',
        },
        'room': {
            'start': '_cmd_start',
            'bot': '_cmd_bot',
            'invite': '_cmd_invite',
            'kick': '_cmd_kick',
            'mode': '_cmd_mode',
            'tier': '_cmd_tier',
        },
        'playing': {
            'discard': '_cmd_discard',
            'tsumo': '_cmd_tsumo',
            'pon': '_cmd_pon',
            'chi': '_cmd_chi',
            'ron': '_cmd_ron',
            'pass': '_cmd_pass',
            'riichi': '_cmd_riichi',
            'abort': '_cmd_abort',
        },
    }

    def __init__(self):
        self._init_rooms()

    def handle_disconnect(self, lobby, player_name):
        location = lobby.get_player_location(player_name)
        if location == 'mahjong_playing':
            room_id = self._player_room.get(player_name)
            room = self._rooms.get(room_id) if room_id else None
            if room and room.state == 'playing' and player_name not in room.bots:
                # 将离线玩家转为 bot，不移除
                room.bots.add(player_name)
                seat = room.get_position(player_name)

                # 清除立直待确认
                if room._riichi_pending and room._riichi_pending.get('seat') == seat:
                    room._riichi_pending = None

                # 如果该玩家正在被等待响应 (pending_action)，自动 pass
                pa = room._pending_action
                if pa and seat in pa.get('waiting', set()):
                    pa['responses'][seat] = 'pass'
                    pa['waiting'].discard(seat)
                    if not pa['waiting']:
                        room._pending_action = None
                        if not room.is_draw():
                            room.next_turn()

                # 清除 _player_room 映射
                self._player_room.pop(player_name, None)

                # 全员离线 → 直接销毁房间，不再调度 bot
                humans = [p for p in room.players if p and p not in room.bots]
                if not humans:
                    self._rooms.pop(room_id, None)
                    return []

                notify = self._notify_room_game(
                    room, f'{player_name} 离线了，已由AI代打~')

                # 触发 bot 调度（如果现在轮到该 bot）
                bot_schedule = self._schedule_bot_turn(room)

                result = {'send_to_players': notify}
                if bot_schedule:
                    result['schedule'] = bot_schedule
                return [result]
        self._remove_player(lobby, player_name)
        return []

    def handle_back(self, lobby, player_name, player_data):
        location = lobby.get_player_location(player_name)
        if location == 'mahjong_playing':
            return self._cmd_abort(lobby, player_name, player_data, '')
        if location == 'mahjong_room':
            return self._cmd_leave(lobby, player_name, player_data, '')
        return self.handle_quit(lobby, player_name, player_data)

    def handle_quit(self, lobby, player_name, player_data):
        self._remove_player(lobby, player_name)
        parent = lobby.get_parent_location(f'{self.game_key}_lobby')
        lobby.set_player_location(player_name, parent)
        # 请求世界地图更新，让客户端显示建筑内地图
        room_data = lobby.get_player_room_data(player_name)
        send_to_caller = []
        if room_data:
            send_to_caller.append({'type': ROOM_UPDATE, 'room_data': room_data})
        send_to_caller.append({'type': GAME, 'text': '离开了麻将。'})
        return {
            'action': 'location_update',
            'location': parent,
            'send_to_caller': send_to_caller,
            'refresh_commands': True,
        }

    # ── 房间管理辅助 ──

    def get_player_room(self, player_name):
        room_id = self._player_room.get(player_name)
        return self._rooms.get(room_id) if room_id else None

    def get_room(self, room_id):
        return self._rooms.get(room_id)

    def join_room(self, room_id, player_name):
        room = self._rooms.get(room_id)
        if not room:
            return None, '房间不存在。'
        if room.state != 'waiting':
            return None, '游戏已经开始。'
        if room.get_position(player_name) >= 0:
            return room, None
        success, msg = room.add_player(player_name)
        if not success:
            return None, msg
        self._player_room[player_name] = room_id
        return room, None

    def send_invite(self, from_name, to_name, room_id):
        self._invites[to_name] = {
            'from': from_name, 'room_id': room_id,
            'time': time.time(),
        }

    def get_invite(self, player_name):
        from ...config import INVITE_EXPIRE
        inv = self._invites.get(player_name)
        if inv and time.time() - inv['time'] > INVITE_EXPIRE:
            self._invites.pop(player_name, None)
            return None
        return inv

    def clear_invite(self, player_name):
        self._invites.pop(player_name, None)

    def get_player_room_data(self, player_name):
        room = self.get_player_room(player_name)
        if not room:
            return None
        if room.state == 'playing':
            seat = room.get_position(player_name)
            return room.get_game_data(seat) if seat >= 0 else room.get_table_data()
        return room.get_table_data()

    def _msg(self, player_name, text):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            seat = room.get_position(player_name)
            board = room.get_game_data(seat) if seat >= 0 else room.get_table_data()
            pa = room._pending_action
            if pa and seat in pa.get('actions_map', {}):
                board['available_actions'] = pa['actions_map'][seat]
                board['action_tile'] = tile_to_chinese(pa['tile'])
        elif room:
            board = room.get_table_data()
        else:
            board = self._lobby_board()
        board['message'] = text
        if board.get('room_state') == 'lobby':
            from ...lobby.help import get_help_welcome
            board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
        return {
            'action': 'mahjong_message',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
        }

    def _remove_player(self, lobby, player_name: str):
        room_id = self._player_room.pop(player_name, None)
        if not room_id:
            return
        room = self._rooms.get(room_id)
        if not room:
            return
        room.remove_player(player_name)
        # 真人全部离开 → 删除房间（无论什么状态，纯机器人房间无意义）
        human = [p for p in room.players if p and p not in room.bots]
        if not human:
            self._rooms.pop(room_id, None)
            return
        # 如果房间空了，删除
        if room.get_player_count() == 0:
            self._rooms.pop(room_id, None)
        elif room.host == player_name:
            # 转移房主
            for p in room.players:
                if p and p not in room.bots:
                    room.host = p
                    break

    def _notify_room(self, room, message, room_data, exclude=None, location=None):
        """通知房间内其他真人"""
        players = {}
        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if not p or p == exclude or p in room.bots:
                continue
            msgs = []
            if message:
                msgs.append({'type': GAME, 'text': message})
            msgs.append({'type': ROOM_UPDATE, 'room_data': room_data})
            if location:
                msgs.append({'type': LOCATION_UPDATE, 'location': location})
            players[p] = msgs
        return players

    def _notify_room_game(self, room, message, exclude=None, location=None,
                           ai_desc=None):
        """通知房间所有真人，每人发各自视角的 game_data"""
        players = {}
        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if not p or p == exclude or p in room.bots:
                continue
            board = room.get_game_data(i)
            if ai_desc:
                board['ai_description'] = ai_desc
                board['ai_priority'] = 'high'
            msgs = []
            if message:
                msgs.append({'type': GAME, 'text': message})
            msgs.append({'type': ROOM_UPDATE, 'room_data': board})
            if location:
                msgs.append({'type': LOCATION_UPDATE, 'location': location})
            players[p] = msgs
        return players

    # ── 指令实现: 大厅 ──

    def _cmd_create(self, lobby, player_name, player_data, args):
        self._remove_player(lobby, player_name)
        room_id = self.gen_room_id()
        while room_id in self._rooms:
            room_id = self.gen_room_id()
        room = MahjongRoom(room_id, player_name)
        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        lobby.set_player_location(player_name, 'mahjong_room')
        mode_label = '东风战' if room.game_mode == 'east' else '南风战'
        tier_label = self._TIER_MAP.get(room.room_tier, room.room_tier)
        return {
            'action': 'mahjong_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': (
                    f'创建了麻将房间 #{room_id}\n'
                    f'模式: {mode_label} | {tier_label}\n'
                    f'座位: 东\n等待其他玩家加入...'
                )},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_room'},
            ],
            'refresh_commands': True,
        }

    def _cmd_rooms(self, lobby, player_name, player_data, args):
        if not self._rooms:
            return self._msg(player_name, '暂无房间。')
        lines = ['当前房间:']
        for room in self._rooms.values():
            label = {'waiting': '等待中', 'playing': '进行中', 'finished': '已结束'}
            count = room.get_player_count()
            lines.append(
                f'  #{room.room_id}  {room.host}  '
                f'{count}/{MAX_PLAYERS}  {label.get(room.state, room.state)}'
            )
        return self._msg(player_name, '\n'.join(lines))

    def _cmd_join(self, lobby, player_name, player_data, args):
        if not args:
            # 无参数 → 弹出可加入房间子菜单
            waiting = [r for r in self._rooms.values() if r.state == 'waiting' and not r.is_full()]
            items = []
            for room in waiting:
                cnt = room.get_player_count()
                label = f'#{room.room_id} {room.host}' if room.host else f'#{room.room_id}'
                items.append({
                    'label': label,
                    'desc': f'{cnt}/{MAX_PLAYERS}',
                    'command': f'/join {room.room_id}',
                })
            return self._select_menu('加入房间', items, '暂无可加入的房间。')
        room_id = args.strip()
        room, error = self.join_room(room_id, player_name)
        if error:
            return self._msg(player_name, error)
        rank_err = self._check_tier_rank(room, player_name, player_data)
        if rank_err:
            room.remove_player(player_name)
            self._player_room.pop(player_name, None)
            return self._msg(player_name, rank_err)
        lobby.set_player_location(player_name, 'mahjong_room')
        pos = room.get_position(player_name)
        pos_name = POSITION_NAMES[pos]
        cnt = room.get_player_count()
        join_msg = (
            f'加入了房间 #{room_id}\n'
            f'座位: {pos_name}\n'
            f'等待开始 ({cnt}/{MAX_PLAYERS})'
        )
        table_data = room.get_table_data()
        notify = self._notify_room(
            room, f"{player_name} 加入了房间 ({room.get_player_count()}/{MAX_PLAYERS})",
            table_data, exclude=player_name)
        return {
            'action': 'mahjong_join',
            'send_to_caller': [
                {'type': GAME, 'text': join_msg},
                {'type': ROOM_UPDATE, 'room_data': table_data},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    def _cmd_invite(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你还没有创建或加入房间。')

        if not args or not args.startswith('@'):
            # 无参数 → 弹出在线好友子菜单
            friends = player_data.get('friends', [])
            online = set(lobby.online_players)  # snapshot
            items = []
            for name in friends:
                if name not in online:
                    continue
                if self.get_player_room(name):
                    continue
                items.append({
                    'label': name,
                    'command': f'/invite @{name}',
                })
            return self._select_menu('邀请好友', items, '没有可邀请的在线好友。')

        target = args[1:].strip()
        friends = player_data.get('friends', [])
        if target not in friends:
            return self._msg(player_name, f'{target} 不是你的好友。')
        if target not in lobby.online_players:
            return self._msg(player_name, f'好友 {target} 不在线。')
        if self.get_player_room(target):
            return self._msg(player_name, f'{target} 已经在一个房间中了。')
        self.send_invite(player_name, target, room.room_id)
        lobby._track_invite(player_name, player_data)
        from ...msg_types import GAME_INVITE
        from ...config import INVITE_EXPIRE
        if lobby.invite_callback:
            lobby.invite_callback(target, {
                'type': GAME_INVITE,
                'from': player_name,
                'game': 'mahjong',
                'room_id': room.room_id,
                'expires_in': INVITE_EXPIRE,
            })
        return self._msg(player_name, f'已向 {target} 发送邀请')

    def _cmd_accept(self, lobby, player_name, player_data, args):
        invite = self.get_invite(player_name)
        if not invite:
            return self._msg(player_name, '你没有收到邀请，或邀请已过期。')
        room_id = invite['room_id']
        self.clear_invite(player_name)
        room, error = self.join_room(room_id, player_name)
        if error:
            return self._msg(player_name, error)
        rank_err = self._check_tier_rank(room, player_name, player_data)
        if rank_err:
            room.remove_player(player_name)
            self._player_room.pop(player_name, None)
            return self._msg(player_name, rank_err)
        lobby.set_player_location(player_name, 'mahjong_room')
        pos = room.get_position(player_name)
        table_data = room.get_table_data()
        notify = self._notify_room(
            room, f"{player_name} 接受邀请加入了房间",
            table_data, exclude=player_name)
        return {
            'action': 'mahjong_accept',
            'send_to_caller': [
                {'type': GAME, 'text': (
                    f'接受邀请加入房间 #{room_id}'
                    f'\n座位: {POSITION_NAMES[pos]}'
                )},
                {'type': ROOM_UPDATE, 'room_data': table_data},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    # ── 指令实现: 房间 ──

    def _cmd_start(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已经开始或已结束。')
        # 检查所有人类玩家的段位是否满足房间要求
        req_rank = self._TIER_RANK_REQ.get(room.room_tier)
        if req_rank:
            from ...systems.ranks import get_rank_index
            req_idx = get_rank_index(req_rank, game_type='mahjong')
            for p in room.players:
                if not p or p in room.bots:
                    continue
                pd = lobby.online_players.get(p)
                if not pd:
                    continue
                mj = pd.get('games', {}).get('mahjong', {})
                p_rank = mj.get('rank', 'beginner_1')
                if get_rank_index(p_rank, game_type='mahjong') < req_idx:
                    from ...systems.ranks import get_rank_name
                    req_name = get_rank_name(req_rank, game_type='mahjong')
                    return self._msg(player_name, f'{p} 的段位不足，需要 {req_name} 以上。')
        if room.get_player_count() < MAX_PLAYERS:
            cnt = room.get_player_count()
            return self._msg(
                player_name,
                f'需要 {MAX_PLAYERS} 人才能开始'
                f'（当前 {cnt}/{MAX_PLAYERS}）。'
                '\n使用 bot 添加机器人。',
            )

        # 首次 or 继续下一局
        if room.round_wind == 0 and room.round_number == 0 and room.honba == 0:
            room.start_game()
            start_msg = f'麻将游戏开始! {room.get_round_name()}'
        else:
            if room.is_game_over():
                # 整场结束，重新开一场
                room.start_game()
                start_msg = f'新的对局开始! {room.get_round_name()}'
            else:
                room.start_next_round()
                start_msg = f'{room.get_round_name()} 开始!'

        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if p:
                lobby.set_player_location(p, 'mahjong_playing')

        # 每个玩家收到自己视角的数据
        send_to_players = self._notify_room_game(
            room, start_msg, location='mahjong_playing',
            ai_desc=start_msg)

        seat = room.get_position(player_name)
        board = room.get_game_data(seat)
        board['ai_description'] = start_msg
        board['ai_priority'] = 'high'
        result = {
            'action': 'mahjong_start',
            'send_to_caller': [
                {'type': GAME, 'text': start_msg},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_playing'},
            ],
            'send_to_players': send_to_players,
            'refresh_commands': True,
        }
        bot_schedule = self._schedule_bot_turn(room)
        if bot_schedule:
            result['schedule'] = bot_schedule
        return result

    def _cmd_leave(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        self._remove_player(lobby, player_name)
        lobby.set_player_location(player_name, 'mahjong_lobby')
        board = self._lobby_board()
        from ...lobby.help import get_help_welcome
        board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT

        # 通知房间剩余真人
        notify = {}
        if room and room.room_id in self._rooms:
            table_data = room.get_table_data()
            notify = self._notify_room(
                room, f'{player_name} 离开了房间',
                table_data, exclude=player_name)

        return {
            'action': 'mahjong_leave',
            'send_to_caller': [
                {'type': GAME, 'text': '离开了房间'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_lobby'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    def _cmd_bot(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你不在任何房间中。')
        if room.host != player_name:
            return self._msg(player_name, '只有房主才能添加机器人。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始，无法添加机器人。')
        if room.room_tier != 'friendly':
            return self._msg(player_name, '只有友人場可以添加机器人。')

        empty = sum(1 for p in room.players if p is None)
        if empty == 0:
            return self._msg(player_name, '房间已满。')

        if not args:
            # 无参数 → 弹出数量子菜单
            items = []
            for n in range(1, empty + 1):
                items.append({
                    'label': f'添加 {n} 个机器人',
                    'command': f'/bot {n}',
                })
            return self._select_menu('添加机器人', items)

        count = 1
        try:
            count = max(1, min(MAX_PLAYERS - 1, int(args.strip())))
        except ValueError:
            count = 1

        added = []
        for _ in range(count):
            if room.is_full():
                break
            ok, name = room.add_bot()
            if ok:
                added.append(name)

        if not added:
            return self._msg(player_name, '无法添加机器人，房间可能已满。')

        names = ', '.join(added)
        table_data = room.get_table_data()
        full_msg = '\n人已齐! 输入 start 开始' if room.is_full() else ''
        notify = self._notify_room(
            room, f"机器人 {names} 加入了房间{full_msg}",
            table_data, exclude=player_name)
        return {
            'action': 'mahjong_bot',
            'send_to_caller': [
                {'type': GAME, 'text': f'已添加机器人: {names}{full_msg}'},
                {'type': ROOM_UPDATE, 'room_data': table_data},
            ],
            'send_to_players': notify,
        }

    def _cmd_kick(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你不在任何房间中。')
        if room.host != player_name:
            return self._msg(player_name, '只有房主才能踢出玩家。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始，无法踢出。')

        if not args:
            # 无参数 → 弹出踢人子菜单
            items = []
            for i in range(MAX_PLAYERS):
                p = room.players[i]
                if p and p != player_name:
                    desc = 'bot' if room.is_bot(p) else ''
                    items.append({
                        'label': p,
                        'desc': desc,
                        'command': f'/kick {i+1}',
                    })
            return self._select_menu('踢出玩家', items, '房间里没有其他玩家。')

        target = args.strip()
        target_name = None
        try:
            idx = int(target) - 1
            if (
                0 <= idx < MAX_PLAYERS
                and room.players[idx]
                and room.players[idx] != player_name
            ):
                target_name = room.players[idx]
        except ValueError:
            if target.startswith('@'):
                name = target[1:]
                for p in room.players:
                    if p and p != player_name and p.lower() == name.lower():
                        target_name = p
                        break

        if not target_name:
            return self._msg(player_name, f'找不到玩家: {target}')

        is_bot = room.is_bot(target_name)
        room.remove_player(target_name)
        if is_bot:
            room.bots.discard(target_name)
        else:
            self._player_room.pop(target_name, None)

        table_data = room.get_table_data()
        return {
            'action': 'mahjong_kick',
            'send_to_caller': [
                {'type': GAME, 'text': f'已踢出: {target_name}'},
                {'type': ROOM_UPDATE, 'room_data': table_data},
            ],
            'send_to_players': self._notify_room(
                room, f'{target_name} 被踢出了房间', table_data, exclude=player_name),
        }

    def _cmd_mode(self, lobby, player_name, player_data, args):
        """切换对局模式（东风/南风）— 无参数弹出子菜单"""
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你不在任何房间中。')
        if room.host != player_name:
            return self._msg(player_name, '只有房主才能更改设置。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始，无法更改。')

        arg = (args or '').strip().lower()
        if not arg:
            current = '东风战' if room.game_mode == 'east' else '南风战'
            return self._select_menu(f'对局模式 (当前: {current})', [
                {'label': '东风战', 'command': '/mode east'},
                {'label': '南风战', 'command': '/mode south'},
            ])

        if arg in ('east', '东', '东风', '东风战'):
            room.game_mode = 'east'
        elif arg in ('south', '南', '南风', '南风战'):
            room.game_mode = 'south'
        else:
            return self._msg(player_name, '无效的模式选项。')

        mode_label = '东风战' if room.game_mode == 'east' else '南风战'
        table_data = room.get_table_data()
        notify = self._notify_room(
            room, f'对局模式已更改为: {mode_label}',
            table_data, exclude=player_name)
        return {
            'action': 'mahjong_mode',
            'send_to_caller': [
                {'type': GAME, 'text': f'已设置为: {mode_label}'},
                {'type': ROOM_UPDATE, 'room_data': table_data},
            ],
            'send_to_players': notify,
        }

    _TIER_MAP = {
        'friendly': '友人場', 'bronze': '銅之間',
        'silver': '銀之間', 'gold': '金之間', 'jade': '玉之間',
    }
    _TIER_ALIAS = {
        '友人': 'friendly', '友人場': 'friendly', '友人场': 'friendly',
        '铜': 'bronze', '銅': 'bronze', '銅之間': 'bronze', '铜之间': 'bronze',
        '银': 'silver', '銀': 'silver', '銀之間': 'silver', '银之间': 'silver',
        '金': 'gold', '金之間': 'gold', '金之间': 'gold',
        '玉': 'jade', '玉之間': 'jade', '玉之间': 'jade',
    }
    # 段位场所需最低段位
    _TIER_RANK_REQ = {
        'friendly': None,
        'bronze': 'beginner_1',
        'silver': 'adept_1',
        'gold': 'expert_1',
        'jade': 'master_1',
    }

    def _check_tier_rank(self, room, player_name, player_data):
        """检查玩家段位是否满足房间要求，不满足返回错误消息字符串"""
        req_rank = self._TIER_RANK_REQ.get(room.room_tier)
        if not req_rank:
            return None
        from ...systems.ranks import get_rank_index, get_rank_name
        req_idx = get_rank_index(req_rank, game_type='mahjong')
        mj = player_data.get('games', {}).get('mahjong', {})
        p_rank = mj.get('rank', 'beginner_1')
        if get_rank_index(p_rank, game_type='mahjong') < req_idx:
            req_name = get_rank_name(req_rank, game_type='mahjong')
            tier_label = self._TIER_MAP.get(room.room_tier, room.room_tier)
            return f'{tier_label} 需要段位 {req_name} 以上。'
        return None

    def _cmd_tier(self, lobby, player_name, player_data, args):
        """设置房间段位 — 无参数弹出子菜单"""
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你不在任何房间中。')
        if room.host != player_name:
            return self._msg(player_name, '只有房主才能更改设置。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始，无法更改。')

        arg = (args or '').strip().lower()
        if not arg:
            current = self._TIER_MAP.get(room.room_tier, '友人場')
            items = [
                {'label': v, 'command': f'/tier {k}'}
                for k, v in self._TIER_MAP.items()
            ]
            return self._select_menu(f'房间段位 (当前: {current})', items)

        tier_key = self._TIER_ALIAS.get(arg) or (arg if arg in self._TIER_MAP else None)
        if not tier_key:
            return self._msg(player_name, '无效的段位选项。')

        room.room_tier = tier_key
        label = self._TIER_MAP[tier_key]
        table_data = room.get_table_data()
        notify = self._notify_room(
            room, f'房间段位已更改为: {label}',
            table_data, exclude=player_name)
        return {
            'action': 'mahjong_tier',
            'send_to_caller': [
                {'type': GAME, 'text': f'已设置为: {label}'},
                {'type': ROOM_UPDATE, 'room_data': table_data},
            ],
            'send_to_players': notify,
        }

    # ── 指令实现: 游戏中 ──

    def _cmd_discard(self, lobby, player_name, player_data, args):
        """打出一张牌 — 通过序号选择（也路由动作指令）"""
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')

        if not args:
            # 展示手牌选择菜单
            seat = room.get_position(player_name)
            if room.current_turn != seat:
                return self._msg(player_name, '还没轮到你。')
            full_hand = sorted(list(room.hands[seat]), key=lambda t: t // 4)
            if room.drawn_tile is not None and room.current_turn == seat:
                full_hand.append(room.drawn_tile)
            items = [{'label': tile_to_chinese(t), 'command': f'/discard {i+1}'}
                     for i, t in enumerate(full_hand)]
            return self._select_menu('选择打出的牌', items)

        arg = args.strip()

        # 路由动作指令（输入框直接输入 ron/pon/pass/tsumo/riichi/chi）
        if arg == 'ron':
            return self._cmd_ron(lobby, player_name, player_data, '')
        if arg == 'pon':
            return self._cmd_pon(lobby, player_name, player_data, '')
        if arg == 'pass':
            return self._cmd_pass(lobby, player_name, player_data, '')
        if arg == 'tsumo':
            return self._cmd_tsumo(lobby, player_name, player_data, '')
        if arg == 'riichi':
            return self._cmd_riichi(lobby, player_name, player_data, '')
        if arg == 'back':
            return self._cmd_riichi_back(lobby, player_name)
        if arg.startswith('riichi'):
            riichi_args = arg[6:].strip() if len(arg) > 6 else ''
            return self._cmd_riichi(lobby, player_name, player_data, riichi_args)
        if arg.startswith('chi'):
            chi_args = arg[3:].strip() if len(arg) > 3 else ''
            return self._cmd_chi(lobby, player_name, player_data, chi_args)

        # 以下是打牌逻辑
        seat = room.get_position(player_name)
        if room._pending_action:
            return self._msg(player_name, '等待其他玩家响应中。')
        if room.current_turn != seat:
            return self._msg(player_name, '还没轮到你。')
        if room.drawn_tile is None and not room.hands[seat]:
            return self._msg(player_name, '无牌可打。')

        # 立直选牌模式
        if room._riichi_pending and room._riichi_pending['seat'] == seat:
            return self._riichi_discard(lobby, room, player_name, seat, arg)

        # 已立直的玩家自动摸切（不允许手动选牌）
        if room.riichi[seat]:
            if room.drawn_tile is not None:
                tile_136 = room.drawn_tile
                return self._do_discard(lobby, room, player_name, seat,
                                        tile_136)
            return self._msg(player_name, '立直中，自动摸切。')

        # 新摸的牌放在最后（与渲染端一致）
        full_hand = sorted(list(room.hands[seat]), key=lambda t: t // 4)
        if room.drawn_tile is not None and room.current_turn == seat:
            full_hand.append(room.drawn_tile)

        # 支持序号输入
        try:
            idx = int(arg)
        except ValueError:
            return self._msg(player_name, f'无效的序号（1~{len(full_hand)}）。')

        if idx < 1 or idx > len(full_hand):
            return self._msg(player_name, f'序号超出范围（1~{len(full_hand)}）。')

        tile_136 = full_hand[idx - 1]
        return self._do_discard(lobby, room, player_name, seat, tile_136)

    def _riichi_discard(self, lobby, room, player_name, seat, arg):
        """立直选牌模式下的打牌"""
        full_hand = sorted(list(room.hands[seat]), key=lambda t: t // 4)
        if room.drawn_tile is not None and room.current_turn == seat:
            full_hand.append(room.drawn_tile)

        try:
            idx = int(arg)
        except ValueError:
            room._riichi_pending = None
            return self._msg(player_name, '无效的序号。')

        valid = room._riichi_pending['valid_indices']
        if idx not in valid:
            room._riichi_pending = None
            return self._msg(
                player_name,
                f'该牌不能听牌。可选序号: {", ".join(str(i) for i in sorted(valid))}')

        if idx < 1 or idx > len(full_hand):
            room._riichi_pending = None
            return self._msg(player_name, f'序号超出范围（1~{len(full_hand)}）。')

        tile_136 = full_hand[idx - 1]
        room._riichi_pending = None

        # 执行立直 + 打牌
        room.do_riichi(seat)
        riichi_msg = f'{player_name} 立直!'
        send_to_others = self._notify_room_game(
            room, riichi_msg, exclude=player_name,
            ai_desc=riichi_msg)
        result = self._do_discard(lobby, room, player_name, seat, tile_136)

        # 合并通知
        if isinstance(result, dict):
            existing = result.get('send_to_players', {})
            for p, msgs in send_to_others.items():
                if p in existing:
                    existing[p] = msgs + existing[p]
                else:
                    existing[p] = msgs
            result['send_to_players'] = existing
            # 在 caller 消息前插入立直通知
            caller_msgs = result.get('send_to_caller', [])
            result['send_to_caller'] = [
                {'type': GAME, 'text': '立直!'}
            ] + caller_msgs
        return result

    def _cmd_riichi_back(self, lobby, player_name):
        """取消立直选牌"""
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '没有进行中的游戏。')
        seat = room.get_position(player_name)
        if not room._riichi_pending or room._riichi_pending['seat'] != seat:
            return self._msg(player_name, '没有待确认的立直。')

        room._riichi_pending = None
        my_board = room.get_game_data(seat)
        return {
            'action': 'mahjong_riichi_cancel',
            'send_to_caller': [
                {'type': GAME, 'text': '已取消立直。'},
                {'type': ROOM_UPDATE, 'room_data': my_board},
            ],
        }

    def _do_discard(self, lobby, room, player_name, seat, tile_136):
        """执行打牌并处理后续流程"""
        if not room.discard_tile(seat, tile_136):
            return self._msg(player_name, '打牌失败。')

        bot_schedule = None

        # 检查其他家是否能 碰/杠/和
        pending_waiting = set()
        pending_actions_map = {}  # seat -> list of action names
        bot_responses = {}  # seat -> action
        for i in range(1, 4):
            other = (seat + i) % 4
            other_p = room.players[other]
            if not other_p:
                continue
            can_ron = room.check_ron(other, tile_136) is not None
            # 振听不能荣和
            if can_ron and room.is_furiten(other):
                can_ron = False
            can_pon = room.can_pon(other, tile_136)
            can_chi = room.can_chi(other, tile_136, seat)
            if not (can_ron or can_pon or can_chi):
                continue
            if other_p in room.bots:
                action = _bot_ai.respond_to_discard(
                    room, other, tile_136, seat)
                if action != 'pass':
                    bot_responses[other] = action
            else:
                pending_waiting.add(other)
                acts = []
                if can_ron:
                    acts.append('ron')
                if can_pon:
                    acts.append('pon')
                if can_chi:
                    acts.append('chi')
                acts.append('pass')
                pending_actions_map[other] = acts

        # bot 响应延迟执行（先让玩家看到弃牌）
        if bot_responses:
            room._pending_bot_response = {
                'tile': tile_136,
                'from_seat': seat,
                'bot_responses': bot_responses,
            }
            # 如果没有真人也在等（仅 bot），schedule 延迟副露
            # 有真人等待时，让真人先决定（ron 优先于 pon/chi）
            if not pending_actions_map:
                bot_schedule = [{'type': 'bot_meld_response',
                                 'room_id': room.room_id,
                                 'game_id': 'mahjong'}]

        actions_available = bool(pending_actions_map)
        if actions_available:
            room._pending_action = {
                'tile': tile_136,
                'from_seat': seat,
                'responses': {},
                'waiting': pending_waiting,
                'actions_map': pending_actions_map,
            }

        if not actions_available and not bot_responses:
            # 流局检查
            if room.is_draw():
                return self._handle_draw(lobby, room, player_name)
            # 下一家
            room.next_turn()
            # 机器人延迟打牌
            bot_schedule = self._schedule_bot_turn(room)
            # 立直玩家自动摸切（非机器人、无自摸）
            if not bot_schedule:
                bot_schedule = self._schedule_riichi_auto(room)

        # 发送更新给所有人
        tile_name_cn = tile_to_chinese(tile_136)
        send_to_players = {}
        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if not p or p == player_name or p in room.bots:
                continue
            board = room.get_game_data(i)
            msgs = []
            if actions_available and i in pending_actions_map:
                board['available_actions'] = pending_actions_map[i]
                board['action_tile'] = tile_name_cn
                board['message'] = f'可以操作: {" / ".join(pending_actions_map[i])}'
            msgs.append({'type': ROOM_UPDATE, 'room_data': board})
            send_to_players[p] = msgs

        my_board = room.get_game_data(seat)
        if actions_available:
            my_board['message'] = '等待其他玩家响应...'

        result = {
            'action': 'mahjong_discard',
            'send_to_caller': [
                {'type': ROOM_UPDATE, 'room_data': my_board},
            ],
            'send_to_players': send_to_players,
        }
        if bot_schedule:
            result['schedule'] = bot_schedule
        return result

    def _cmd_tsumo(self, lobby, player_name, player_data, args):
        """自摸"""
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        seat = room.get_position(player_name)
        if room.current_turn != seat:
            return self._msg(player_name, '还没轮到你。')

        win_info = room.check_tsumo(seat)
        if not win_info:
            return self._msg(player_name, '现在不能自摸。')

        return self._handle_win(lobby, room, player_name, seat, win_info, is_tsumo=True)

    def _cmd_ron(self, lobby, player_name, player_data, args):
        """荣和"""
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if not room._pending_action:
            return self._msg(player_name, '没有可以荣和的牌。')

        seat = room.get_position(player_name)
        tile = room._pending_action['tile']
        win_info = room.check_ron(seat, tile)
        if not win_info:
            return self._msg(player_name, '不能荣和这张牌。')

        return self._handle_win(
            lobby, room, player_name, seat,
            win_info, is_tsumo=False,
        )

    def _cmd_pon(self, lobby, player_name, player_data, args):
        """碰"""
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if not room._pending_action:
            return self._msg(player_name, '没有可以碰的牌。')

        seat = room.get_position(player_name)
        tile = room._pending_action['tile']
        if not room.can_pon(seat, tile):
            return self._msg(player_name, '不能碰这张牌。')

        # 从河里移除那张牌(最后一张弃牌)
        from_seat = room._pending_action['from_seat']
        if room.discards[from_seat] and room.discards[from_seat][-1] == tile:
            room.discards[from_seat].pop()

        room.do_pon(seat, tile)
        room._pending_action = None
        room._pending_bot_response = None
        room.current_turn = seat
        room.drawn_tile = None  # 碰之后需要打一张牌，不摸牌

        send_to_players = self._notify_room_game(
            room, f'{player_name} 碰!', exclude=player_name)

        my_board = room.get_game_data(seat)
        my_board['must_discard'] = True
        return {
            'action': 'mahjong_pon',
            'send_to_caller': [
                {'type': GAME, 'text': '碰! 请打出一张牌。'},
                {'type': ROOM_UPDATE, 'room_data': my_board},
            ],
            'send_to_players': send_to_players,
        }

    def _cmd_chi(self, lobby, player_name, player_data, args):
        """吃"""
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if not room._pending_action:
            return self._msg(player_name, '没有可以吃的牌。')

        seat = room.get_position(player_name)
        tile = room._pending_action['tile']
        from_seat = room._pending_action['from_seat']

        if not room.can_chi(seat, tile, from_seat):
            return self._msg(player_name, '不能吃这张牌。')

        # 构建与显示序号一致的有序手牌
        sorted_hand = sorted(list(room.hands[seat]), key=lambda t: t // 4)

        if not args:
            # 枚举所有合法吃牌组合，生成菜单
            t34 = tile // 4
            suit = t34 // 9
            rank = t34 % 9
            items = []
            if suit < 3:  # 数牌才能吃
                for d1, d2 in [(-2, -1), (-1, 1), (1, 2)]:
                    need = [t34 + d1, t34 + d2]
                    if any(n < suit * 9 or n >= (suit + 1) * 9 or n < 0 for n in need):
                        continue
                    idxs = []
                    used = set()
                    for n34 in need:
                        for i, t136 in enumerate(sorted_hand):
                            if t136 // 4 == n34 and i not in used:
                                idxs.append(i + 1)
                                used.add(i)
                                break
                    if len(idxs) == 2:
                        names = [tile_to_chinese(sorted_hand[i - 1]) for i in idxs]
                        items.append({
                            'label': f'{names[0]} + {names[1]} + {tile_to_chinese(tile)}',
                            'command': f'/discard chi {idxs[0]} {idxs[1]}',
                        })
            if not items:
                return self._msg(player_name, '没有可吃的组合。')
            return self._select_menu('吃牌', items)

        # 解析要组合的牌
        parts = args.strip().split()
        if len(parts) != 2:
            return self._msg(player_name, '需要指定两张手牌。')

        combo = []
        for p in parts:
            try:
                idx = int(p)
            except ValueError:
                return self._msg(player_name, '无效的序号。')
            if idx < 1 or idx > len(sorted_hand):
                return self._msg(player_name, f'序号超出范围（1~{len(sorted_hand)}）。')
            found = sorted_hand[idx - 1]
            if found in combo:
                return self._msg(player_name, '不能选择同一张牌两次。')
            combo.append(found)

        # 验证三张能组成顺子
        vals = sorted([tile // 4, combo[0] // 4, combo[1] // 4])
        if not (vals[1] == vals[0] + 1 and vals[2] == vals[1] + 1):
            return self._msg(player_name, '这三张牌不能组成顺子。')
        # 必须同花色
        if vals[0] // 9 != vals[2] // 9 or vals[0] >= 27:
            return self._msg(player_name, '必须是同花色数牌。')

        if room.discards[from_seat] and room.discards[from_seat][-1] == tile:
            room.discards[from_seat].pop()

        room.do_chi(seat, tile, combo)
        room._pending_action = None
        room._pending_bot_response = None
        room.current_turn = seat
        room.drawn_tile = None

        send_to_players = self._notify_room_game(
            room, f'{player_name} 吃!', exclude=player_name)

        my_board = room.get_game_data(seat)
        my_board['must_discard'] = True
        return {
            'action': 'mahjong_chi',
            'send_to_caller': [
                {'type': GAME, 'text': '吃! 请打出一张牌。'},
                {'type': ROOM_UPDATE, 'room_data': my_board},
            ],
            'send_to_players': send_to_players,
        }

    def _cmd_pass(self, lobby, player_name, player_data, args):
        """放弃 碰/吃/和 的机会"""
        room = self.get_player_room(player_name)
        if not room or not room._pending_action:
            return self._msg(player_name, '没有需要响应的操作。')

        seat = room.get_position(player_name)
        # 放弃荣和 → 同巡振听
        acts = room._pending_action.get('actions_map', {}).get(seat, [])
        if 'ron' in acts:
            room.temp_furiten[seat] = True
            # 立直中放弃荣和 → 永久振听（立直振听）用 temp 标记即可，
            # 立直中不会再清除 temp_furiten（next_turn 清除但立直自动摸切）
        room._pending_action['responses'][seat] = 'pass'
        room._pending_action['waiting'].discard(seat)

        # 所有人都 pass 了
        if not room._pending_action['waiting']:
            room._pending_action = None

            # 检查是否有延迟的 bot 副露响应
            if getattr(room, '_pending_bot_response', None):
                send_to_players = self._notify_room_game(
                    room, '', exclude=player_name)
                my_seat = room.get_position(player_name)
                my_board = room.get_game_data(my_seat)
                return {
                    'action': 'mahjong_pass',
                    'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': my_board}],
                    'send_to_players': send_to_players,
                    'schedule': [{'type': 'bot_meld_response',
                                  'room_id': room.room_id,
                                  'game_id': 'mahjong'}],
                }

            if room.is_draw():
                return self._handle_draw(lobby, room, player_name)
            room.next_turn()
            bot_schedule = self._schedule_bot_turn(room)
            if not bot_schedule:
                bot_schedule = self._schedule_riichi_auto(room)

            send_to_players = self._notify_room_game(room, '', exclude=player_name)
            my_seat = room.get_position(player_name)
            my_board = room.get_game_data(my_seat)
            result = {
                'action': 'mahjong_pass',
                'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': my_board}],
                'send_to_players': send_to_players,
            }
            if bot_schedule:
                result['schedule'] = bot_schedule
            return result

        return self._msg(player_name, '已放弃，等待其他玩家。')

    def _cmd_riichi(self, lobby, player_name, player_data, args):
        """宣言立直 — riichi <序号> 一步完成"""
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        seat = room.get_position(player_name)
        if room.current_turn != seat:
            return self._msg(player_name, '还没轮到你。')
        if not room.can_riichi(seat):
            return self._msg(player_name, '现在不能立直。')

        options = room.get_riichi_options(seat)
        if not options:
            return self._msg(player_name, '没有可以听牌的打法。')

        valid_indices = set()
        for opt in options:
            valid_indices.add(opt['idx'])

        arg = args.strip() if args else ''
        if not arg:
            # 展示可立直打出的牌菜单
            items = []
            for opt in options:
                tile_name = opt.get('tile_chinese', f'牌{opt["idx"]}')
                waiting_info = ', '.join(
                    w['name'] for w in opt.get('waiting', []))
                label = f'{tile_name} → 听 {waiting_info}' if waiting_info else tile_name
                items.append({
                    'label': label,
                    'command': f'/discard riichi {opt["idx"]}',
                })
            return self._select_menu('立直 — 选择打出的牌', items)

        room._riichi_pending = {
            'seat': seat,
            'valid_indices': valid_indices,
        }
        return self._riichi_discard(lobby, room, player_name, seat, arg)

    def _cmd_abort(self, lobby, player_name, player_data, args):
        """中途退出"""
        room = self.get_player_room(player_name)
        if not room:
            return self._cmd_leave(lobby, player_name, player_data, '')

        if not args or args.strip() != 'y':
            return self._select_menu('确认退出？游戏将结束', [
                {'label': '确认退出', 'command': '/abort y'},
                {'label': '取消', 'command': ''},
            ])

        room.state = 'finished'
        finished_data = room.get_finished_data()
        finished_data['message'] = f'{player_name} 中途退出，游戏结束。'

        notify = self._notify_room(
            room, f'{player_name} 中途退出，游戏结束。',
            finished_data, exclude=player_name, location='mahjong_room')

        # 所有人回到房间
        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if p and p not in room.bots:
                lobby.set_player_location(p, 'mahjong_room')

        room.state = 'waiting'

        self._remove_player(lobby, player_name)
        lobby.set_player_location(player_name, 'mahjong_lobby')
        board = self._lobby_board()
        from ...lobby.help import get_help_welcome
        board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
        return {
            'action': 'mahjong_abort',
            'send_to_caller': [
                {'type': GAME, 'text': '退出了游戏'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_lobby'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    # ── 游戏结束处理 ──

    # 名次分表: tier → (1st, 2nd, 3rd, 4th)
    _PLACEMENT_PTS = {
        1: (+30, +10, -10, -30),   # 初心
        2: (+40, +10, -10, -40),   # 雀士
        3: (+50, +10, -20, -50),   # 雀杰
        4: (+60, +15, -30, -60),   # 雀豪
        5: (+75, +15, -35, -75),   # 雀圣
        6: (+90, +20, -40, -90),   # 魂天
    }

    # 经验/金币段位 tier 倍率
    _TIER_MULT = {int(k): v for k, v in _REWARDS.get('tier_multiplier', {}).items()}

    def _calc_rank_points(self, room, seat, rank_idx, tier):
        """计算单个座位的段位点变化。

        公式: 名次分(按 tier) + (终点 - 25000) / 1000
        Bot 场: ×0.5；tier ≥ 3 时正分归零。
        """
        placement = self._PLACEMENT_PTS.get(tier, self._PLACEMENT_PTS[1])
        base = placement[rank_idx] + (room.scores[seat] - INITIAL_SCORE) / 1000
        pts = int(round(base))

        has_bot = bool(room.bots)
        if has_bot:
            pts = int(round(pts * 0.5))
            if tier >= 3 and pts > 0:
                pts = 0
        return pts

    def _apply_rank_changes(self, lobby, room, rankings):
        """段位结算 — 返回 {player_name: {pts, old_rank, new_rank, ...}}"""
        from ...systems.ranks import (
            get_rank_info, get_rank_index, get_rank_order,
            get_title_id_from_rank,
        )
        from ...player.manager import PlayerManager

        _gk = self.game_key
        rank_order = get_rank_order(_gk)
        changes = {}

        for rank_idx, seat in enumerate(rankings):
            p = room.players[seat]
            if not p or p in room.bots:
                continue
            pd = lobby.online_players.get(p)
            if not pd:
                continue
            gd = pd.setdefault(_gk, {})
            cur_rank = gd.get('rank', rank_order[0])
            cur_pts = gd.get('rank_points', 0)
            info = get_rank_info(cur_rank, _gk)
            tier = info.get('tier', 1)

            delta = self._calc_rank_points(room, seat, rank_idx, tier)
            new_pts = cur_pts + delta
            new_rank = cur_rank
            promoted = False
            demoted = False

            # 升段
            pts_up = info.get('points_up')
            if pts_up and new_pts >= pts_up:
                idx = get_rank_index(cur_rank, _gk)
                if idx < len(rank_order) - 1:
                    new_rank = rank_order[idx + 1]
                    new_pts = 0
                    promoted = True

            # 降段 (points_down is not None 才可降)
            if not promoted and new_pts < 0:
                if info.get('points_down') is not None:
                    idx = get_rank_index(cur_rank, _gk)
                    if idx > 0:
                        prev = rank_order[idx - 1]
                        prev_info = get_rank_info(prev, _gk)
                        new_rank = prev
                        new_pts = (prev_info.get('points_up', 40) or 40) // 2
                        demoted = True
                else:
                    new_pts = 0

            gd['rank'] = new_rank
            gd['rank_points'] = new_pts
            if get_rank_index(new_rank, _gk) > get_rank_index(
                    gd.get('max_rank', rank_order[0]), _gk):
                gd['max_rank'] = new_rank

            # 升段授予头衔
            if promoted:
                title_id = get_title_id_from_rank(new_rank)
                if title_id:
                    from ...player.schema import default_titles
                    titles = pd.setdefault('titles', default_titles())
                    if title_id not in titles['owned']:
                        titles['owned'].append(title_id)

            PlayerManager.save_player_data(p, pd)

            from ...systems.ranks import get_rank_name
            changes[p] = {
                'delta': delta,
                'old_rank': cur_rank,
                'old_rank_name': get_rank_name(cur_rank, _gk),
                'new_rank': new_rank,
                'new_rank_name': get_rank_name(new_rank, _gk),
                'new_pts': new_pts,
                'promoted': promoted,
                'demoted': demoted,
            }
        return changes

    def _apply_game_rewards(self, lobby, room):
        """对局结束时发放经验/金币（友人場不发）+ 段位结算 + 统计更新。
        返回 (描述文本, rank_changes dict)。
        """
        if room.room_tier == 'friendly':
            return '', {}

        from ...systems.leveling import check_level_up
        from ...systems.ranks import get_rank_info, get_rank_name
        from ...player.manager import PlayerManager

        rankings = sorted(range(MAX_PLAYERS),
                          key=lambda i: room.scores[i], reverse=True)
        reward_base = self._REWARDS.get('placement', [
            [2400, 500], [1500, 250], [900, 0], [400, -100]])

        # 段位结算
        rank_changes = self._apply_rank_changes(lobby, room, rankings)

        # 经验/金币 — 按最高 tier 倍率
        max_tier = 1
        for seat in range(MAX_PLAYERS):
            p = room.players[seat]
            if p and p not in room.bots:
                pd = lobby.online_players.get(p)
                if pd:
                    gd = pd.get(self.game_key, {})
                    info = get_rank_info(gd.get('rank', 'beginner_1'),
                                         self.game_key)
                    max_tier = max(max_tier, info.get('tier', 1))
        mult = self._TIER_MULT.get(max_tier, 1.0)

        lines = []
        for rank_idx, seat in enumerate(rankings):
            p = room.players[seat]
            if not p or p in room.bots:
                continue
            pd = lobby.online_players.get(p)
            if not pd:
                continue
            base_exp, base_gold = reward_base[rank_idx]
            # 点数加成: (终点 - 25000) / 1000 × 系数
            sf = self._REWARDS.get('score_factor', {})
            score_delta = (room.scores[seat] - INITIAL_SCORE) / 1000
            base_exp += score_delta * sf.get('exp_per_1k', 0)
            base_gold += score_delta * sf.get('gold_per_1k', 0)
            exp_gain = max(0, int(round(base_exp * mult)))
            gold_gain = int(round(base_gold * mult))
            pd['exp'] = pd.get('exp', 0) + exp_gain
            pd['gold'] = max(0, pd.get('gold', 0) + gold_gain)
            lvl_ups = check_level_up(pd)

            # report_game_result 更新统计
            if rank_idx == 0:
                result, delta_stats = 'win', {'wins': 1}
            elif rank_idx == 3:
                result, delta_stats = 'loss', {'losses': 1}
            else:
                result, delta_stats = 'draw', {'draws': 1}
            self.report_game_result(lobby, p, pd, result, delta_stats)

            pos_label = ['1st', '2nd', '3rd', '4th'][rank_idx]
            parts = [f'{p}({pos_label}): +{exp_gain}exp']
            if gold_gain > 0:
                parts.append(f'+{gold_gain}金币')
            elif gold_gain < 0:
                parts.append(f'{gold_gain}金币')
            if lvl_ups:
                parts.append(f'升级! Lv.{lvl_ups[-1]}')
            rc = rank_changes.get(p)
            if rc:
                d = rc['delta']
                sign = '+' if d >= 0 else ''
                parts.append(f'[{sign}{d}pt]')
                if rc['promoted']:
                    parts.append(f'升段→{rc["new_rank_name"]}')
                elif rc['demoted']:
                    parts.append(f'降段→{rc["new_rank_name"]}')
            lines.append(' '.join(parts))
        desc = '\n' + '\n'.join(lines) if lines else ''
        return desc, rank_changes

    def _handle_win(self, lobby, room, player_name, winner_seat, win_info, is_tsumo):
        """处理和牌 — 一步发送全部数据，客户端渐进展示"""
        from_seat = None
        ron_tile = None
        if not is_tsumo and room._pending_action:
            from_seat = room._pending_action['from_seat']
            ron_tile = room._pending_action['tile']
        room._pending_action = None
        room._pending_bot_response = None

        room.apply_win(winner_seat, win_info, is_tsumo, from_seat)
        room.advance_round(dealer_won=(winner_seat == room.dealer))

        win_type = '自摸' if is_tsumo else '荣和'
        winner = room.players[winner_seat]

        win_data = room.get_win_data(
            winner_seat, win_info, is_tsumo, from_seat, ron_tile)

        msg = f'{winner} {win_type}!'
        if room.is_game_over():
            rewards, rank_changes = self._apply_game_rewards(lobby, room)
            msg += '\n\n对局结束!' + rewards
            win_data['message'] = '对局结束!' + rewards
            win_data['rank_changes'] = rank_changes
        else:
            win_data['next_round'] = room.get_round_name()

        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if p and p not in room.bots:
                lobby.set_player_location(p, 'mahjong_room')

        room.state = 'waiting'

        notify = self._notify_room(
            room, msg, win_data,
            exclude=player_name, location='mahjong_room')

        result = {
            'action': 'mahjong_win',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': win_data},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }
        human_players = [p for p in room.players if p and p not in room.bots]
        if human_players:
            result['refresh_status'] = human_players
        return result

    def _handle_draw(self, lobby, room, player_name):
        """流局"""
        room.apply_draw()
        # 流局: 亲家听牌则连庄
        dealer_tenpai = False
        full = room.get_full_hand(room.dealer)
        tiles_34 = hand_to_34(full)
        try:
            sh = _shanten.calculate_shanten(tiles_34)
            dealer_tenpai = sh <= 0
        except Exception:
            pass
        room.advance_round(dealer_won=dealer_tenpai)

        room.state = 'finished'
        finished_data = room.get_finished_data()
        msg = '流局! 牌山已空。'

        if room.is_game_over():
            rewards, rank_changes = self._apply_game_rewards(lobby, room)
            msg += '\n\n对局结束!' + rewards
            finished_data['rank_changes'] = rank_changes
        else:
            finished_data['next_round'] = room.get_round_name()

        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if p and p not in room.bots:
                lobby.set_player_location(p, 'mahjong_room')

        notify = self._notify_room(
            room, msg, finished_data, exclude=player_name, location='mahjong_room')

        room.state = 'waiting'

        result = {
            'action': 'mahjong_draw',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': finished_data},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }
        human_players = [p for p in room.players if p and p not in room.bots]
        if human_players:
            result['refresh_status'] = human_players
        return result

    # ── 机器人 AI ──

    def _schedule_riichi_auto(self, room):
        """立直玩家自动摸切 — 检查无自摸时安排自动打牌"""
        seat = room.current_turn
        p = room.players[seat]
        if not p or p in room.bots:
            return []
        if not room.riichi[seat]:
            return []
        if room.state != 'playing' or room.drawn_tile is None:
            return []
        # 有自摸时让玩家自行决定
        tsumo = room.check_tsumo(seat)
        if tsumo and tsumo.get('han', 0) and tsumo['han'] >= 1:
            return []
        return [{'game_id': 'mahjong', 'type': 'riichi_auto',
                 'room_id': room.room_id}]

    def _schedule_bot_turn(self, room):
        """返回一个 schedule 条目，让调度器延迟执行 bot 回合"""
        current = room.players[room.current_turn]
        if not current or current not in room.bots:
            return []
        if room.state != 'playing':
            return []
        # 需要有摸牌或手牌（碰/吃后的打牌）
        if room.drawn_tile is None and not room.hands[room.current_turn]:
            return []
        return [{'game_id': 'mahjong', 'type': 'bot_turn', 'room_id': room.room_id}]

    def _execute_one_bot_turn(self, lobby, room):
        """执行一步机器人动作，返回 (continue_bot, send_to_players)"""
        current = room.players[room.current_turn]
        if not current or current not in room.bots:
            return False, {}
        if room.state != 'playing':
            return False, {}

        seat = room.current_turn

        # 检查自摸
        win_info = _bot_ai.should_tsumo(room, seat)
        if win_info:
            self._bot_win(lobby, room, seat, win_info)
            return False, {}

        # 选择弃牌
        hand = room.get_full_hand(seat)
        if not hand:
            return False, {}
        best_tile = _bot_ai.choose_discard(room, seat)

        bot_name = room.players[seat]
        room.discard_tile(seat, best_tile)

        if room.is_draw():
            send_to_players = self._notify_room_game(room, '')
            room._bot_draw = True
            return False, send_to_players

        # 检查其他家响应（包括 bot）
        pending_waiting = set()
        pending_actions_map = {}
        bot_responses = {}  # seat -> action
        for i in range(1, 4):
            other = (seat + i) % 4
            other_p = room.players[other]
            if not other_p:
                continue

            can_ron = room.check_ron(other, best_tile) is not None
            can_pon = room.can_pon(other, best_tile)
            can_chi = room.can_chi(other, best_tile, seat)

            if not (can_ron or can_pon or can_chi):
                continue

            if other_p in room.bots:
                # bot 立即决策
                action = _bot_ai.respond_to_discard(
                    room, other, best_tile, seat)
                if action != 'pass':
                    bot_responses[other] = action
            else:
                # 真人等待响应
                pending_waiting.add(other)
                acts = []
                if can_ron:
                    acts.append('ron')
                if can_pon:
                    acts.append('pon')
                if can_chi:
                    acts.append('chi')
                acts.append('pass')
                pending_actions_map[other] = acts

        # bot 有响应时延迟执行（先让弃牌显示给玩家看）
        if bot_responses:
            room._pending_bot_response = {
                'tile': best_tile,
                'from_seat': seat,
                'bot_responses': bot_responses,
            }
            if not pending_actions_map:
                # 仅 bot 响应，直接发弃牌画面
                send_to_players = self._notify_room_game(room, '')
                return False, send_to_players
            # 也有真人要响应 — 同时设 _pending_action，让真人先决定

        if pending_actions_map:
            room._pending_action = {
                'tile': best_tile,
                'from_seat': seat,
                'responses': {},
                'waiting': pending_waiting,
                'actions_map': pending_actions_map,
            }
            tile_name_cn = tile_to_chinese(best_tile)
            send_to_players = {}
            for i in range(MAX_PLAYERS):
                p = room.players[i]
                if not p or p in room.bots:
                    continue
                board = room.get_game_data(i)
                msgs = []
                if i in pending_actions_map:
                    board['available_actions'] = pending_actions_map[i]
                    board['action_tile'] = tile_name_cn
                msgs.append({'type': ROOM_UPDATE, 'room_data': board})
                send_to_players[p] = msgs
            return False, send_to_players

        room.next_turn()

        send_to_players = self._notify_room_game(room, '')

        next_current = room.players[room.current_turn]
        continue_bot = (
            next_current and next_current in room.bots
            and room.state == 'playing'
            and (room.drawn_tile is not None or room.hands[room.current_turn])
        )
        return continue_bot, send_to_players

    def _execute_bot_response(self, lobby, room, tile, from_seat, bot_responses):
        """执行 bot 对弃牌的响应，返回 (continue_bot, send_to_players) 或 None"""
        # 优先级: ron > pon > chi
        for action in ('ron', 'pon', 'chi'):
            for resp_seat, resp_action in bot_responses.items():
                if resp_action != action:
                    continue
                if action == 'ron':
                    win_info = room.check_ron(resp_seat, tile)
                    if win_info:
                        self._bot_win_ron(
                            lobby, room, resp_seat, tile, win_info, from_seat)
                        return False, {}
                elif action == 'pon':
                    return self._bot_do_pon(lobby, room, resp_seat, tile, from_seat)
                elif action == 'chi':
                    return self._bot_do_chi(lobby, room, resp_seat, tile, from_seat)
        return None

    def _bot_win_ron(self, lobby, room, seat, tile, win_info, from_seat):
        """bot 荣和 — 生成完整数据"""
        if room.discards[from_seat] and room.discards[from_seat][-1] == tile:
            room.discards[from_seat].pop()
        room._pending_action = None

        bot_name = room.players[seat]
        room.apply_win(seat, win_info, is_tsumo=False, from_seat=from_seat)
        room.advance_round(dealer_won=(seat == room.dealer))

        win_data = room.get_win_data(
            seat, win_info, is_tsumo=False,
            from_seat=from_seat, ron_tile=tile)
        msg = f'{bot_name} 荣和!'

        if room.is_game_over():
            rewards, rank_changes = self._apply_game_rewards(lobby, room)
            msg += '\n\n对局结束!' + rewards
            win_data['message'] = '对局结束!' + rewards
            win_data['rank_changes'] = rank_changes
        else:
            win_data['next_round'] = room.get_round_name()

        room.state = 'waiting'
        room._bot_win_result = {'msg': msg, 'win_data': win_data}

    def _bot_do_pon(self, lobby, room, seat, tile, from_seat):
        """bot 碰（仅副露，不弃牌），下一轮 bot turn 再弃"""
        if room.discards[from_seat] and room.discards[from_seat][-1] == tile:
            room.discards[from_seat].pop()
        room.do_pon(seat, tile)
        room._pending_action = None
        room.current_turn = seat
        room.drawn_tile = None

        bot_name = room.players[seat]
        send_to_players = self._notify_room_game(room, f'{bot_name} 碰!')
        return True, send_to_players

    def _bot_do_chi(self, lobby, room, seat, tile, from_seat):
        """bot 吃（仅副露，不弃牌），下一轮 bot turn 再弃"""
        combo = _bot_ai.best_chi_combo(room, seat, tile)
        if not combo:
            return None

        if room.discards[from_seat] and room.discards[from_seat][-1] == tile:
            room.discards[from_seat].pop()
        room.do_chi(seat, tile, combo)
        room._pending_action = None
        room.current_turn = seat
        room.drawn_tile = None

        bot_name = room.players[seat]
        send_to_players = self._notify_room_game(room, f'{bot_name} 吃!')
        return True, send_to_players

    def _bot_win(self, lobby, room, seat, win_info):
        """机器人自摸和牌 — 生成完整数据"""
        bot_name = room.players[seat]
        room.apply_win(seat, win_info, is_tsumo=True)
        room.advance_round(dealer_won=(seat == room.dealer))

        win_data = room.get_win_data(seat, win_info, is_tsumo=True)
        msg = f'{bot_name} 自摸!'

        if room.is_game_over():
            rewards, rank_changes = self._apply_game_rewards(lobby, room)
            msg += '\n\n对局结束!' + rewards
            win_data['message'] = '对局结束!' + rewards
            win_data['rank_changes'] = rank_changes
        else:
            win_data['next_round'] = room.get_round_name()

        room.state = 'waiting'
        room._bot_win_result = {'msg': msg, 'win_data': win_data}


# ── Bot 调度器 ──

import threading


class MahjongBotScheduler:
    """延迟执行机器人回合"""

    from ...config import BOT_DELAY

    def __init__(self, server):
        self._server = server
        self._timers: dict[str, threading.Timer] = {}

    def _get_engine(self):
        lobby = self._server.lobby_engine
        return lobby._get_engine('mahjong', None)

    def handle_schedule(self, task):
        """由 result_dispatcher 调用"""
        task_type = task.get('type', '')
        room_id = task.get('room_id', '')
        if not room_id:
            return
        if task_type == 'bot_turn':
            self._schedule(room_id)
        elif task_type == 'bot_meld_response':
            self._schedule_meld_response(room_id)
        elif task_type == 'riichi_auto':
            self._schedule_riichi(room_id)

    def _schedule(self, room_id: str):
        """安排一个延迟的 bot 回合"""
        self.cancel(room_id)
        t = threading.Timer(self.BOT_DELAY, self._run_bot_turn, args=(room_id,))
        t.daemon = True
        self._timers[room_id] = t
        t.start()

    def cancel(self, room_id: str):
        old = self._timers.pop(room_id, None)
        if old:
            old.cancel()

    def _schedule_riichi(self, room_id: str):
        """安排一个延迟的立直自动摸切"""
        self.cancel(room_id)
        t = threading.Timer(
            self.BOT_DELAY, self._run_riichi_auto, args=(room_id,))
        t.daemon = True
        self._timers[room_id] = t
        t.start()

    def _schedule_meld_response(self, room_id: str):
        """安排一个延迟的 bot 副露响应"""
        self.cancel(room_id)
        t = threading.Timer(
            self.BOT_DELAY, self._run_meld_response, args=(room_id,))
        t.daemon = True
        self._timers[room_id] = t
        t.start()

    def _run_meld_response(self, room_id: str):
        """Timer 回调 — 执行延迟的 bot 副露响应（碰/吃/荣）"""
        self._timers.pop(room_id, None)
        lobby = self._server.lobby_engine
        engine = self._get_engine()
        if not engine:
            return
        room = engine._rooms.get(room_id)
        if not room or room.state != 'playing':
            return

        pending = getattr(room, '_pending_bot_response', None)
        if not pending:
            return
        room._pending_bot_response = None

        tile = pending['tile']
        from_seat = pending['from_seat']
        bot_responses = pending['bot_responses']

        result = engine._execute_bot_response(lobby, room, tile, from_seat, bot_responses)
        if result is None:
            # 所有 bot 最终 pass，继续正常流程
            room.next_turn()
            send_to_players = engine._notify_room_game(room, '')
            next_current = room.players[room.current_turn]
            continue_bot = (
                next_current and next_current in room.bots
                and room.state == 'playing'
                and (room.drawn_tile is not None or room.hands[room.current_turn])
            )
            if send_to_players:
                self._server.dispatch_game_result({
                    'action': 'mahjong_bot_discard',
                    'send_to_players': send_to_players,
                })
            if continue_bot:
                self._schedule(room_id)
            return

        continue_bot, send_to_players = result

        # bot 和牌 — 一步发送完整数据
        bot_result = getattr(room, '_bot_win_result', None)
        if bot_result:
            room._bot_win_result = None
            for i in range(MAX_PLAYERS):
                p = room.players[i]
                if p and p not in room.bots:
                    lobby.set_player_location(p, 'mahjong_room')
            notify = engine._notify_room(
                room, bot_result['msg'], bot_result['win_data'],
                location='mahjong_room')
            dispatch_result = {
                'action': 'mahjong_win',
                'send_to_players': notify,
                'refresh_commands': True,
            }
            human_players = [p for p in room.players if p and p not in room.bots]
            if human_players:
                dispatch_result['refresh_status'] = human_players
            self._server.dispatch_game_result(dispatch_result)
            return

        if send_to_players:
            self._server.dispatch_game_result({
                'action': 'mahjong_bot_meld',
                'send_to_players': send_to_players,
            })

        if continue_bot:
            self._schedule(room_id)

    def _run_riichi_auto(self, room_id: str):
        """Timer 回调 — 立直玩家自动摸切"""
        self._timers.pop(room_id, None)
        lobby = self._server.lobby_engine
        engine = self._get_engine()
        if not engine:
            return
        room = engine._rooms.get(room_id)
        if not room or room.state != 'playing':
            return
        seat = room.current_turn
        p = room.players[seat]
        if not p or p in room.bots or not room.riichi[seat]:
            return
        if room.drawn_tile is None:
            return

        # 安全检查：有自摸时不自动打牌
        tsumo = room.check_tsumo(seat)
        if tsumo and tsumo.get('han', 0) >= 1:
            return

        tile_136 = room.drawn_tile
        result = engine._do_discard(lobby, room, p, seat, tile_136)
        if result and isinstance(result, dict):
            # 把 caller 消息移到 send_to_players
            caller_msgs = result.pop('send_to_caller', [])
            if caller_msgs:
                players = result.setdefault('send_to_players', {})
                existing = players.get(p, [])
                players[p] = [
                    {'type': GAME, 'text': '立直中，自动摸切。'}
                ] + caller_msgs + existing
            # 处理 schedule (可能触发下一个 bot turn)
            for task in result.pop('schedule', []):
                self.handle_schedule(task)
            self._server.dispatch_game_result(result)

    def _run_bot_turn(self, room_id: str):
        """Timer 回调 — 执行一步 bot 动作"""
        self._timers.pop(room_id, None)
        lobby = self._server.lobby_engine
        engine = self._get_engine()
        if not engine:
            return
        room = engine._rooms.get(room_id)
        if not room or room.state != 'playing':
            return

        continue_bot, send_to_players = engine._execute_one_bot_turn(lobby, room)

        # bot 和牌 — 一步发送完整数据
        bot_result = getattr(room, '_bot_win_result', None)
        if bot_result:
            room._bot_win_result = None
            for i in range(MAX_PLAYERS):
                p = room.players[i]
                if p and p not in room.bots:
                    lobby.set_player_location(p, 'mahjong_room')
            notify = engine._notify_room(
                room, bot_result['msg'], bot_result['win_data'],
                location='mahjong_room')
            dispatch_result = {
                'action': 'mahjong_win',
                'send_to_players': notify,
                'refresh_commands': True,
            }
            human_players = [p for p in room.players if p and p not in room.bots]
            if human_players:
                dispatch_result['refresh_status'] = human_players
            self._server.dispatch_game_result(dispatch_result)
            return

        # 流局
        if getattr(room, '_bot_draw', False):
            room._bot_draw = False
            room.apply_draw()
            dealer_tenpai = False
            full = room.get_full_hand(room.dealer)
            tiles_34 = hand_to_34(full)
            try:
                sh = _shanten.calculate_shanten(tiles_34)
                dealer_tenpai = sh <= 0
            except Exception:
                pass
            room.advance_round(dealer_won=dealer_tenpai)
            room.state = 'finished'
            finished_data = room.get_finished_data()
            msg = '流局! 牌山已空。'
            if not room.is_game_over():
                finished_data['next_round'] = room.get_round_name()
            for i in range(MAX_PLAYERS):
                p = room.players[i]
                if p and p not in room.bots:
                    lobby.set_player_location(p, 'mahjong_room')
            notify = engine._notify_room(
                room, msg, finished_data, location='mahjong_room')
            room.state = 'waiting'
            # 先发弃牌更新，再发流局结果
            if send_to_players:
                self._server.dispatch_game_result({
                    'action': 'mahjong_bot_discard',
                    'send_to_players': send_to_players,
                })
            result = {
                'action': 'mahjong_draw',
                'send_to_players': notify,
                'refresh_commands': True,
            }
            self._server.dispatch_game_result(result)
            return

        if send_to_players:
            result = {
                'action': 'mahjong_bot_discard',
                'send_to_players': send_to_players,
            }
            self._server.dispatch_game_result(result)

        # 有延迟的 bot 副露响应待处理
        if getattr(room, '_pending_bot_response', None):
            self._schedule_meld_response(room_id)
        elif continue_bot:
            self._schedule(room_id)
        elif room.state == 'playing':
            # bot 回合结束后若下家是立直玩家，安排自动摸切
            riichi_sched = engine._schedule_riichi_auto(room)
            for task in riichi_sched:
                self.handle_schedule(task)


def create_bot_scheduler(server):
    return MahjongBotScheduler(server)

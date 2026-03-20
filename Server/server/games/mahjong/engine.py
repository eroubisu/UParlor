"""日本麻将游戏引擎 — 指令路由 + 机器人 AI

房间状态管理由 room.py (MahjongRoom) 负责。
牌编码/显示由 tiles.py 负责。
本模块仅负责: 指令分发、消息组装、机器人决策。
"""

from __future__ import annotations

import os
import random
import string

from mahjong.shanten import Shanten

from ...game_core.protocol import BaseGameEngine
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE

from .room import MahjongRoom, MAX_PLAYERS
from .tiles import tile_to_str, tile_to_chinese, str_to_tile34, hand_to_34, POSITION_NAMES

_dir = os.path.dirname(__file__)
_shanten = Shanten()


def _load_help() -> str:
    path = os.path.join(_dir, 'help.txt')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


_HELP_TEXT = _load_help()


def _gen_room_id() -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))


class MahjongEngine(BaseGameEngine):
    """麻将游戏引擎 — 房间制

    所有游戏反馈通过 ROOM_UPDATE 传递到客户端游戏面板。
    """

    game_key = 'mahjong'

    def __init__(self):
        self._rooms: dict[str, MahjongRoom] = {}
        self._player_room: dict[str, str] = {}
        self._invites: dict[str, dict] = {}
        self.pending_confirms: dict[str, dict] = {}

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        cmd_name = cmd.lstrip('/')
        location = lobby.get_player_location(player_name)

        if location == 'mahjong_lobby':
            if cmd_name == 'create':
                return self._cmd_create(lobby, player_name)
            if cmd_name == 'rooms':
                return self._cmd_rooms(player_name)
            if cmd_name == 'join':
                return self._cmd_join(lobby, player_name, args)
            if cmd_name == 'accept':
                return self._cmd_accept(lobby, player_name, player_data)

        elif location == 'mahjong_room':
            if cmd_name == 'start':
                return self._cmd_start(lobby, player_name)
            if cmd_name == 'bot':
                return self._cmd_bot(lobby, player_name, args)
            if cmd_name == 'invite':
                return self._cmd_invite(lobby, player_name, player_data, args)
            if cmd_name == 'kick':
                return self._cmd_kick(lobby, player_name, args)

        elif location == 'mahjong_playing':
            if cmd_name == 'discard':
                return self._cmd_discard(lobby, player_name, args)
            if cmd_name == 'tsumo':
                return self._cmd_tsumo(lobby, player_name)
            if cmd_name == 'pon':
                return self._cmd_pon(lobby, player_name)
            if cmd_name == 'chi':
                return self._cmd_chi(lobby, player_name, args)
            if cmd_name == 'ron':
                return self._cmd_ron(lobby, player_name)
            if cmd_name == 'pass':
                return self._cmd_pass(lobby, player_name)
            if cmd_name == 'riichi':
                return self._cmd_riichi(lobby, player_name)

        return None

    def handle_disconnect(self, lobby, player_name):
        self._remove_player(lobby, player_name)
        return []

    def handle_back(self, lobby, player_name, player_data):
        location = lobby.get_player_location(player_name)
        if location == 'mahjong_playing':
            return self._cmd_abort(lobby, player_name)
        if location == 'mahjong_room':
            return self._cmd_leave(lobby, player_name)
        return self.handle_quit(lobby, player_name, player_data)

    def handle_quit(self, lobby, player_name, player_data):
        self._remove_player(lobby, player_name)
        lobby.set_player_location(player_name, 'world_gamehall')
        return {
            'action': 'location_update',
            'location': 'world_gamehall',
            'message': '离开了麻将。',
            'refresh_commands': True,
        }

    def get_welcome_message(self, player_data):
        board = self._lobby_board()
        board['doc'] = _HELP_TEXT
        return {
            'send_to_caller': [
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_lobby'},
            ],
            'location': 'mahjong_lobby',
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
        self._invites[to_name] = {'from': from_name, 'room_id': room_id}

    def get_invite(self, player_name):
        return self._invites.get(player_name)

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

    def _lobby_board(self) -> dict:
        return {'game_type': 'mahjong', 'room_state': 'lobby'}

    def _msg(self, player_name, text):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            seat = room.get_position(player_name)
            board = room.get_game_data(seat) if seat >= 0 else room.get_table_data()
        elif room:
            board = room.get_table_data()
        else:
            board = self._lobby_board()
        board['message'] = text
        if board.get('room_state') == 'lobby':
            board['doc'] = _HELP_TEXT
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
        # 如果游戏进行中且真人不足，中止游戏
        if room.state == 'playing':
            human = [p for p in room.players if p and p not in room.bots]
            if not human:
                del self._rooms[room_id]
                return
        # 如果房间空了，删除
        if room.get_player_count() == 0:
            del self._rooms[room_id]
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

    def _notify_room_game(self, room, message, exclude=None, location=None):
        """通知房间所有真人，每人发各自视角的 game_data"""
        players = {}
        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if not p or p == exclude or p in room.bots:
                continue
            board = room.get_game_data(i)
            msgs = []
            if message:
                msgs.append({'type': GAME, 'text': message})
            msgs.append({'type': ROOM_UPDATE, 'room_data': board})
            if location:
                msgs.append({'type': LOCATION_UPDATE, 'location': location})
            players[p] = msgs
        return players

    # ── 指令实现: 大厅 ──

    def _cmd_create(self, lobby, player_name):
        self._remove_player(lobby, player_name)
        room_id = _gen_room_id()
        while room_id in self._rooms:
            room_id = _gen_room_id()
        room = MahjongRoom(room_id, player_name)
        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        lobby.set_player_location(player_name, 'mahjong_room')
        return {
            'action': 'mahjong_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': (
                    f'创建了麻将房间 #{room_id}\n'
                    f'座位: 东\n等待其他玩家加入...'
                )},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_room'},
            ],
            'refresh_commands': True,
        }

    def _cmd_rooms(self, player_name):
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

    def _cmd_join(self, lobby, player_name, args):
        if not args:
            return self._msg(player_name, '用法: join <房间ID>')
        room_id = args.strip()
        room, error = self.join_room(room_id, player_name)
        if error:
            return self._msg(player_name, error)
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
        if not args or not args.startswith('@'):
            return self._msg(player_name, '用法: invite @玩家名')
        target = args[1:].strip()
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你还没有创建或加入房间。')
        if target not in lobby.online_players:
            return self._msg(player_name, f'玩家 {target} 不在线。')
        if target == player_name:
            return self._msg(player_name, '不能邀请自己。')
        if self.get_player_room(target):
            return self._msg(player_name, f'{target} 已经在一个房间中了。')
        self.send_invite(player_name, target, room.room_id)
        lobby._track_invite(player_name, player_data)
        from ...msg_types import GAME_INVITE
        if lobby.invite_callback:
            lobby.invite_callback(target, {
                'type': GAME_INVITE,
                'from': player_name,
                'game': 'mahjong',
                'room_id': room.room_id,
                'message': (
                    f' {player_name} 邀请你加入麻将房间!'
                    '\n输入 /play mahjong 然后 /accept 接受邀请'
                )
            })
        return self._msg(player_name, f'已向 {target} 发送邀请')

    def _cmd_accept(self, lobby, player_name, player_data):
        invite = self.get_invite(player_name)
        if not invite:
            return self._msg(player_name, '你没有收到邀请，或邀请已过期。')
        room_id = invite['room_id']
        self.clear_invite(player_name)
        room, error = self.join_room(room_id, player_name)
        if error:
            return self._msg(player_name, error)
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

    def _cmd_start(self, lobby, player_name):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已经开始或已结束。')
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
            room, start_msg, location='mahjong_playing')

        seat = room.get_position(player_name)
        board = room.get_game_data(seat)
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

    def _cmd_leave(self, lobby, player_name):
        self._remove_player(lobby, player_name)
        lobby.set_player_location(player_name, 'mahjong_lobby')
        board = self._lobby_board()
        board['doc'] = _HELP_TEXT
        return {
            'action': 'mahjong_leave',
            'send_to_caller': [
                {'type': GAME, 'text': '离开了房间'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_lobby'},
            ],
            'refresh_commands': True,
        }

    def _cmd_bot(self, lobby, player_name, args):
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你不在任何房间中。')
        if room.host != player_name:
            return self._msg(player_name, '只有房主才能添加机器人。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始，无法添加机器人。')

        count = 1
        if args:
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

    def _cmd_kick(self, lobby, player_name, args):
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你不在任何房间中。')
        if room.host != player_name:
            return self._msg(player_name, '只有房主才能踢出玩家。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始，无法踢出。')

        if not args:
            players_list = []
            for i in range(MAX_PLAYERS):
                p = room.players[i]
                if p and p != player_name:
                    mark = " (bot)" if room.is_bot(p) else ""
                    players_list.append(f"  {i+1}. {p}{mark}")
            if not players_list:
                return self._msg(player_name, '房间里没有其他玩家。')
            body = '\n'.join(players_list)
            return self._msg(
                player_name,
                f'用法: kick <编号>\n\n当前玩家:\n{body}',
            )

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

    # ── 指令实现: 游戏中 ──

    def _cmd_discard(self, lobby, player_name, args):
        """打出一张牌 — 通过序号选择（也路由动作指令）"""
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')

        if not args:
            return self._msg(player_name, '输入序号打出对应的牌。')

        arg = args.strip()

        # 路由动作指令（输入框直接输入 ron/pon/pass/tsumo/riichi/chi）
        if arg == 'ron':
            return self._cmd_ron(lobby, player_name)
        if arg == 'pon':
            return self._cmd_pon(lobby, player_name)
        if arg == 'pass':
            return self._cmd_pass(lobby, player_name)
        if arg == 'tsumo':
            return self._cmd_tsumo(lobby, player_name)
        if arg == 'riichi':
            return self._cmd_riichi(lobby, player_name)
        if arg.startswith('chi'):
            chi_args = arg[3:].strip() if len(arg) > 3 else ''
            return self._cmd_chi(lobby, player_name, chi_args)

        # 以下是打牌逻辑
        seat = room.get_position(player_name)
        if room.current_turn != seat:
            return self._msg(player_name, '还没轮到你。')
        if room.drawn_tile is None and not room.hands[seat]:
            return self._msg(player_name, '无牌可打。')

        # 新摸的牌放在最后（与渲染端一致）
        full_hand = sorted(list(room.hands[seat]), key=lambda t: t // 4)
        if room.drawn_tile is not None and room.current_turn == seat:
            full_hand.append(room.drawn_tile)

        # 支持序号输入
        arg = args.strip()
        try:
            idx = int(arg)
        except ValueError:
            return self._msg(player_name, f'请输入序号（1~{len(full_hand)}）。')

        if idx < 1 or idx > len(full_hand):
            return self._msg(player_name, f'序号超出范围（1~{len(full_hand)}）。')

        tile_136 = full_hand[idx - 1]

        if not room.discard_tile(seat, tile_136):
            return self._msg(player_name, '打牌失败。')

        discard_name = tile_to_chinese(tile_136)

        # 检查其他家是否能 碰/杠/和
        actions_available = False
        pending_waiting = set()
        pending_actions_map = {}  # seat -> list of action names
        for i in range(1, 4):
            other = (seat + i) % 4
            other_p = room.players[other]
            if not other_p:
                continue
            # 机器人自动 pass
            if other_p in room.bots:
                continue
            can_ron = room.check_ron(other, tile_136) is not None
            can_pon = room.can_pon(other, tile_136)
            can_chi = room.can_chi(other, tile_136, seat)
            if can_ron or can_pon or can_chi:
                actions_available = True
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

        if actions_available:
            room._pending_action = {
                'tile': tile_136,
                'from_seat': seat,
                'responses': {},
                'waiting': pending_waiting,
                'actions_map': pending_actions_map,
            }

        if not actions_available:
            # 流局检查
            if room.is_draw():
                return self._handle_draw(lobby, room, player_name)
            # 下一家
            room.next_turn()
            # 机器人延迟打牌
            bot_schedule = self._schedule_bot_turn(room)

        # 发送更新给所有人
        tile_name_cn = tile_to_chinese(tile_136)
        send_to_players = {}
        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if not p or p == player_name or p in room.bots:
                continue
            board = room.get_game_data(i)
            msgs = [{'type': GAME, 'text': f'{player_name} 打出 {discard_name}'}]
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
        if not actions_available and bot_schedule:
            result['schedule'] = bot_schedule
        return result

    def _cmd_tsumo(self, lobby, player_name):
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

    def _cmd_ron(self, lobby, player_name):
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

        room._pending_action = None
        return self._handle_win(
            lobby, room, player_name, seat,
            win_info, is_tsumo=False,
        )

    def _cmd_pon(self, lobby, player_name):
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

    def _cmd_chi(self, lobby, player_name, args):
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

        if not args:
            return self._msg(player_name, '用法: chi <牌1> <牌2> (手中要出的两张牌)')

        # 解析要组合的牌
        parts = args.strip().split()
        if len(parts) != 2:
            return self._msg(player_name, '需要指定两张手牌。用法: chi <牌1> <牌2>')

        combo = []
        for p in parts:
            t34 = str_to_tile34(p)
            if t34 is None:
                return self._msg(player_name, f'无法识别: {p}')
            # 找手牌中的 136 编码
            found = None
            for t in room.hands[seat]:
                if t // 4 == t34 and t not in combo:
                    found = t
                    break
            if found is None:
                return self._msg(player_name, f'手中没有 {p}')
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

    def _cmd_pass(self, lobby, player_name):
        """放弃 碰/吃/和 的机会"""
        room = self.get_player_room(player_name)
        if not room or not room._pending_action:
            return self._msg(player_name, '没有需要响应的操作。')

        seat = room.get_position(player_name)
        room._pending_action['responses'][seat] = 'pass'
        room._pending_action['waiting'].discard(seat)

        # 所有人都 pass 了
        if not room._pending_action['waiting']:
            room._pending_action = None
            if room.is_draw():
                return self._handle_draw(lobby, room, player_name)
            room.next_turn()
            bot_schedule = self._schedule_bot_turn(room)

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

    def _cmd_riichi(self, lobby, player_name):
        """宣言立直"""
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        seat = room.get_position(player_name)
        if room.current_turn != seat:
            return self._msg(player_name, '还没轮到你。')
        if not room.can_riichi(seat):
            return self._msg(player_name, '现在不能立直。')

        room.do_riichi(seat)
        send_to_players = self._notify_room_game(
            room, f'{player_name} 立直!', exclude=player_name)
        my_board = room.get_game_data(seat)
        my_board['must_discard'] = True
        return {
            'action': 'mahjong_riichi',
            'send_to_caller': [
                {'type': GAME, 'text': '立直! 请打出一张牌。'},
                {'type': ROOM_UPDATE, 'room_data': my_board},
            ],
            'send_to_players': send_to_players,
        }

    def _cmd_abort(self, lobby, player_name):
        """中途退出"""
        room = self.get_player_room(player_name)
        if not room:
            return self._cmd_leave(lobby, player_name)

        room.state = 'finished'
        finished_data = room.get_finished_data(None, None)
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
        board['doc'] = _HELP_TEXT
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

    def _handle_win(self, lobby, room, player_name, winner_seat, win_info, is_tsumo):
        """处理和牌"""
        from_seat = None
        if not is_tsumo and room._pending_action:
            from_seat = room._pending_action['from_seat']

        room.apply_win(winner_seat, win_info, is_tsumo, from_seat)
        room.advance_round(dealer_won=(winner_seat == room.dealer))

        win_type = '自摸' if is_tsumo else '荣和'
        winner = room.players[winner_seat]
        cost = win_info['cost']
        yaku_str = ', '.join(win_info.get('yaku', []))
        msg = (
            f'{winner} {win_type}!\n'
            f'{win_info["han"]}翻{win_info["fu"]}符  {cost}点\n'
            f'役: {yaku_str}'
        )

        if room.is_game_over():
            room.state = 'finished'
            finished_data = room.get_finished_data(winner_seat, win_info)
            msg += '\n\n对局结束!'
        else:
            room.state = 'finished'
            finished_data = room.get_finished_data(winner_seat, win_info)
            finished_data['next_round'] = room.get_round_name()

        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if p and p not in room.bots:
                lobby.set_player_location(p, 'mahjong_room')

        notify = self._notify_room(
            room, msg, finished_data, exclude=player_name, location='mahjong_room')

        room.state = 'waiting'

        return {
            'action': 'mahjong_win',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': finished_data},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

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
        finished_data = room.get_finished_data(None, None)
        msg = '流局! 牌山已空。'

        if not room.is_game_over():
            finished_data['next_round'] = room.get_round_name()

        for i in range(MAX_PLAYERS):
            p = room.players[i]
            if p and p not in room.bots:
                lobby.set_player_location(p, 'mahjong_room')

        notify = self._notify_room(
            room, msg, finished_data, exclude=player_name, location='mahjong_room')

        room.state = 'waiting'

        return {
            'action': 'mahjong_draw',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE, 'room_data': finished_data},
                {'type': LOCATION_UPDATE, 'location': 'mahjong_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    # ── 机器人 AI ──

    def _schedule_bot_turn(self, room):
        """返回一个 schedule 条目，让调度器延迟执行 bot 回合"""
        current = room.players[room.current_turn]
        if not current or current not in room.bots:
            return []
        if room.state != 'playing' or room.drawn_tile is None:
            return []
        return [{'game_id': 'mahjong', 'type': 'bot_turn', 'room_id': room.room_id}]

    def _execute_one_bot_turn(self, lobby, room):
        """执行一步机器人动作，返回 (continue_bot, send_to_players)"""
        current = room.players[room.current_turn]
        if not current or current not in room.bots:
            return False, {}
        if room.state != 'playing' or room.drawn_tile is None:
            return False, {}

        seat = room.current_turn

        # 检查自摸
        tsumo = room.check_tsumo(seat)
        if tsumo and tsumo.get('han', 0) and tsumo['han'] >= 1:
            self._bot_win(lobby, room, seat, tsumo)
            return False, {}

        # 简单 AI
        hand = room.get_full_hand(seat)
        best_tile = hand[-1]
        best_shanten = 99
        for t in hand:
            test_hand = [x for x in hand if x != t]
            tiles_34 = [0] * 34
            for x in test_hand:
                tiles_34[x // 4] += 1
            try:
                sh = _shanten.calculate_shanten(tiles_34)
                if sh < best_shanten:
                    best_shanten = sh
                    best_tile = t
            except Exception:
                pass

        bot_name = room.players[seat]
        room.discard_tile(seat, best_tile)
        discard_name = tile_to_chinese(best_tile)

        # 发送弃牌更新给真人
        send_to_players = self._notify_room_game(
            room, f'{bot_name} 打出 {discard_name}')

        if room.is_draw():
            # 流局 — 标记到 room 上供调度器处理
            room._bot_draw = True
            return False, send_to_players

        room.next_turn()

        next_current = room.players[room.current_turn]
        continue_bot = (
            next_current and next_current in room.bots
            and room.state == 'playing' and room.drawn_tile is not None
        )
        return continue_bot, send_to_players

    def _bot_win(self, lobby, room, seat, win_info):
        """机器人自摸和牌"""
        bot_name = room.players[seat]
        room.apply_win(seat, win_info, is_tsumo=True)
        room.advance_round(dealer_won=(seat == room.dealer))
        room.state = 'finished'
        room.last_win_info = win_info
        room.last_winner_seat = seat
        cost = win_info['cost']
        room.last_win_message = (
            f'{bot_name} 自摸!\n'
            f'{win_info["han"]}翻{win_info["fu"]}符  {cost}点\n'
            f'役: {", ".join(win_info.get("yaku", []))}'
        )


# ── Bot 调度器 ──

import threading


class MahjongBotScheduler:
    """延迟执行机器人回合，每步间隔 1 秒"""

    BOT_DELAY = 1.0

    def __init__(self, server):
        self._server = server
        self._timers: dict[str, threading.Timer] = {}

    def _get_engine(self):
        lobby = self._server.lobby_engine
        return lobby._get_engine('mahjong', None)

    def handle_schedule(self, task):
        """由 result_dispatcher 调用"""
        if task.get('type') == 'bot_turn':
            room_id = task.get('room_id', '')
            if room_id:
                self._schedule(room_id)

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

        # bot 可能自摸赢了
        if room.state == 'finished' and room.last_win_message:
            msg = room.last_win_message
            win_info = room.last_win_info
            winner_seat = room.last_winner_seat
            finished_data = room.get_finished_data(winner_seat, win_info)
            for i in range(MAX_PLAYERS):
                p = room.players[i]
                if p and p not in room.bots:
                    lobby.set_player_location(p, 'mahjong_room')
            notify = engine._notify_room(
                room, msg, finished_data, location='mahjong_room')
            room.state = 'waiting'
            result = {
                'action': 'mahjong_bot_win',
                'send_to_players': notify,
                'refresh_commands': True,
            }
            self._server.dispatch_game_result(result)
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
            finished_data = room.get_finished_data(None, None)
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

        if continue_bot:
            self._schedule(room_id)


def create_bot_scheduler(server):
    return MahjongBotScheduler(server)

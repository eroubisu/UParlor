"""国际象棋游戏引擎 — 房间制 2 人对战

python-chess 处理全部规则校验，Stockfish 驱动 Bot。
位置层级: chess_lobby → chess_room (等待) → chess_playing (游戏中)
"""

from __future__ import annotations

import os
import random
import time

from ...core.protocol import BaseGameEngine
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE
from .room import ChessRoom

_dir = os.path.dirname(__file__)
_data_dir = os.path.join(_dir, 'data')
MAX_PLAYERS = 2


def _load_help() -> str:
    path = os.path.join(_data_dir, 'help.txt')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return ''


def _load_rewards() -> dict:
    import json
    path = os.path.join(_data_dir, 'rewards.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


class ChessEngine(BaseGameEngine):
    """国际象棋引擎 — 房间制 2 人"""

    game_key = 'chess'
    display_name = '国际象棋'
    _HELP_TEXT = _load_help()
    _REWARDS = _load_rewards()

    _GLOBAL_COMMANDS: dict[str, str] = {}
    _COMMAND_MAP = {
        'lobby': {
            'create': '_cmd_create',
            'rooms': '_cmd_rooms',
            'accept': '_cmd_accept',
        },
        'room': {
            'start': '_cmd_start',
            'invite': '_cmd_invite',
            'kick': '_cmd_kick',
            'bot': '_cmd_bot',
        },
        'playing': {
            'move': '_cmd_move',
            'resign': '_cmd_resign',
            'draw': '_cmd_draw',
            'accept': '_cmd_accept_draw',
            'reject': '_cmd_reject_draw',
        },
    }

    def __init__(self):
        self._init_rooms()

    def get_player_room(self, player_name: str) -> ChessRoom | None:
        room_id = self._player_room.get(player_name)
        return self._rooms.get(room_id) if room_id else None

    def get_player_room_data(self, player_name: str) -> dict | None:
        room = self.get_player_room(player_name)
        return room.get_game_data(viewer=player_name) if room else None

    def handle_disconnect(self, lobby, player_name):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            seat = room.get_seat(player_name)
            if seat is not None:
                room.resign(seat)
                opponent = room.players[1 - seat]
                if opponent and not room.is_bot(opponent):
                    opp_data = lobby.online_players.get(opponent)
                    if opp_data:
                        result = self._handle_game_over(lobby, room, opponent, opp_data)
                        self._remove_player(player_name)
                        if isinstance(result, dict):
                            result.setdefault('send_to_caller', []).insert(0,
                                {'type': GAME, 'text': f'{player_name} 断线了，你获胜！'})
                            return result
                        return []
        self._remove_player(player_name)
        return []

    def handle_back(self, lobby, player_name, player_data):
        location = lobby.get_player_location(player_name)
        if location == 'chess_playing':
            return self._cmd_resign(lobby, player_name, player_data, '')
        if location == 'chess_room':
            return self._cmd_leave(lobby, player_name, player_data, '')
        return self.handle_quit(lobby, player_name, player_data)

    def handle_quit(self, lobby, player_name, player_data):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            seat = room.get_seat(player_name)
            if seat is not None:
                room.resign(seat)
                self._notify_opponent_win(lobby, room, player_name)
        self._remove_player(player_name)
        parent = lobby.get_parent_location(f'{self.game_key}_lobby')
        lobby.set_player_location(player_name, parent)
        return {
            'action': 'location_update',
            'location': parent,
            'send_to_caller': [
                {'type': GAME, 'text': '离开了国际象棋。'},
            ],
            'refresh_commands': True,
        }

    # ── 辅助 ──

    def _remove_player(self, player_name: str):
        room = self.get_player_room(player_name)
        if room:
            room.remove_player(player_name)
            room_id = self._player_room.pop(player_name, None)
            if not any(room.players) and room_id:
                self._rooms.pop(room_id, None)
            elif room.host == player_name:
                for p in room.players:
                    if p:
                        room.host = p
                        break

    def _notify_room(self, room, message, exclude, location=None, room_data_fn=None):
        """通知房间内其他玩家"""
        players = {}
        for p in room.players:
            if not p or p == exclude or room.is_bot(p):
                continue
            rd = room_data_fn(p) if room_data_fn else room.get_game_data(viewer=p)
            msgs = []
            if message:
                msgs.append({'type': GAME, 'text': message})
            msgs.append({'type': ROOM_UPDATE, 'room_data': rd})
            if location:
                msgs.append({'type': LOCATION_UPDATE, 'location': location})
            players[p] = msgs
        return players

    def _notify_opponent_win(self, lobby, room, loser_name):
        """通知对手获胜（用于 resign/disconnect after game end）"""
        seat = room.get_seat(loser_name)
        if seat is None:
            return
        opp = room.players[1 - seat]
        if opp and not room.is_bot(opp):
            lobby.set_player_location(opp, 'chess_room')

    # ── 大厅指令 ──

    def _cmd_create(self, lobby, player_name, player_data, args):
        self._remove_player(player_name)
        room_id = self.gen_room_id()
        while room_id in self._rooms:
            room_id = self.gen_room_id()
        room = ChessRoom(room_id, player_name)
        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        lobby.set_player_location(player_name, 'chess_room')
        return {
            'action': 'chess_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': f'创建了象棋房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': 'chess_room'},
            ],
            'refresh_commands': True,
        }

    def _cmd_rooms(self, lobby, player_name, player_data, args):
        if not self._rooms:
            return self._msg(player_name, '暂无房间。')
        lines = ['当前房间:']
        for room in self._rooms.values():
            label = {'waiting': '等待中', 'playing': '进行中', 'finished': '已结束'}
            lines.append(
                f'  #{room.room_id}  {room.host}'
                f'  {room.player_count}/2人  {label.get(room.state, room.state)}'
            )
        return self._msg(player_name, '\n'.join(lines))

    def _cmd_accept(self, lobby, player_name, player_data, args):
        from ...config import INVITE_EXPIRE
        inv = self._invites.pop(player_name, None)
        if not inv or time.time() - inv['time'] > INVITE_EXPIRE:
            return self._msg(player_name, '没有待处理的邀请。')
        room_id = inv['room_id']
        room = self._rooms.get(room_id)
        if not room or room.state != 'waiting' or room.is_full():
            return self._msg(player_name, '房间已不可用。')

        self._remove_player(player_name)
        room.add_player(player_name)
        self._player_room[player_name] = room_id
        lobby.set_player_location(player_name, 'chess_room')

        td = room.get_table_data()
        notify = self._notify_room(room, f'{player_name} 加入了房间',
                                       exclude=player_name,
                                       room_data_fn=lambda _: td)
        return {
            'action': 'chess_join',
            'send_to_caller': [
                {'type': GAME, 'text': f'加入了房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': td},
                {'type': LOCATION_UPDATE, 'location': 'chess_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    # ── 房间指令 ──

    def _cmd_start(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if not room.is_full():
            return self._msg(player_name, '需要 2 名玩家才能开始。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已经开始。')

        # 随机分配黑白
        if random.random() < 0.5:
            room.players[0], room.players[1] = room.players[1], room.players[0]
        room.start()

        for p in room.players:
            if p:
                lobby.set_player_location(p, 'chess_playing')

        white, black = room.players
        start_msg = f'国际象棋开始！白方: {white}  黑方: {black}'

        notify = self._notify_room(
            room, start_msg, exclude=player_name, location='chess_playing')

        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'chess_start',
            'send_to_caller': [
                {'type': GAME, 'text': start_msg},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'chess_playing'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _cmd_bot(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.is_full():
            return self._msg(player_name, '房间已满。')

        difficulty = (args or 'normal').strip().lower()
        if difficulty not in ('easy', 'normal', 'hard'):
            difficulty = 'normal'

        bot_name = f'Bot({difficulty})'
        room.add_player(bot_name)
        room.bots.add(bot_name)

        td = room.get_table_data()
        return {
            'action': 'chess_bot_added',
            'send_to_caller': [
                {'type': GAME, 'text': f'添加了 {bot_name}'},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
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
        from ...config import INVITE_EXPIRE
        if lobby.invite_callback:
            lobby.invite_callback(target, {
                'type': GAME_INVITE, 'from': player_name,
                'game': 'chess', 'room_id': room.room_id,
                'expires_in': INVITE_EXPIRE,
            })
        return self._msg(player_name, f'已向 {target} 发送邀请。')

    def _cmd_kick(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '只有房主才能踢人。')
        others = [p for p in room.players if p and p != player_name]
        if not others:
            return self._msg(player_name, '房间里没有其他玩家。')

        if not args or not args.startswith('@'):
            items = [{'label': p, 'command': f'/kick @{p}'} for p in others]
            return self._select_menu('踢出玩家', items)

        target = args[1:].strip()
        if target not in others:
            return self._msg(player_name, f'{target} 不在房间中。')
        is_bot = room.is_bot(target)
        room.remove_player(target)
        self._player_room.pop(target, None)

        td = room.get_table_data()
        result = {
            'action': 'chess_kick',
            'send_to_caller': [
                {'type': GAME, 'text': f'已踢出 {target}'},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
        }
        if not is_bot:
            lobby.set_player_location(target, 'chess_lobby')
            lobby_board = self._lobby_board()
            from ...lobby.help import get_help_welcome
            lobby_board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
            result['send_to_players'] = {
                target: [
                    {'type': GAME, 'text': '你被踢出了房间。'},
                    {'type': ROOM_UPDATE, 'room_data': lobby_board},
                    {'type': LOCATION_UPDATE, 'location': 'chess_lobby'},
                ],
            }
            result['refresh_commands'] = True
        return result

    def _cmd_leave(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        self._remove_player(player_name)
        lobby.set_player_location(player_name, 'chess_lobby')
        board = self._lobby_board()
        from ...lobby.help import get_help_welcome
        board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT

        result = {
            'action': 'chess_leave',
            'send_to_caller': [
                {'type': GAME, 'text': '离开了房间'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'chess_lobby'},
            ],
            'refresh_commands': True,
        }
        if room:
            opp = [p for p in room.players if p and p != player_name and not room.is_bot(p)]
            if opp:
                td = room.get_table_data()
                result['send_to_players'] = {
                    opp[0]: [
                        {'type': GAME, 'text': f'{player_name} 离开了房间'},
                        {'type': ROOM_UPDATE, 'room_data': td},
                    ],
                }
        return result

    # ── 游戏中指令 ──

    def _cmd_move(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.current_player() != player_name:
            return self._msg(player_name, '还没有轮到你。')

        uci = (args or '').strip().lower()
        if not uci:
            # 展示合法走法菜单
            moves = list(room.board.legal_moves)
            items = [{'label': m.uci(), 'command': f'/move {m.uci()}'} for m in moves]
            return self._select_menu('选择走法', items)

        move = room.try_move(uci)
        if not move:
            return self._msg(player_name, f'非法走法: {uci}')

        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)

        # 游戏继续
        board_caller = room.get_game_data(viewer=player_name)
        notify = self._notify_room(room, '', exclude=player_name)

        return {
            'action': 'chess_move',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board_caller}],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _cmd_resign(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._cmd_leave(lobby, player_name, player_data, '')
        seat = room.get_seat(player_name)
        if seat is None:
            return self._msg(player_name, '你不在游戏中。')

        if not args or args.strip() != 'y':
            return self._select_menu('确认认输？', [
                {'label': '确认认输', 'command': '/resign y'},
                {'label': '取消', 'command': ''},
            ])

        room.resign(seat)
        return self._handle_game_over(lobby, room, player_name, player_data)

    def _cmd_draw(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        seat = room.get_seat(player_name)
        if seat is None:
            return self._msg(player_name, '你不在游戏中。')

        opp_seat = 1 - seat
        opp = room.players[opp_seat]
        if opp and room.is_bot(opp):
            # Bot 自行决定是否接受和棋 (简单: 子力差不多就接受)
            room.accept_draw()
            return self._handle_game_over(lobby, room, player_name, player_data)

        room._draw_offer_from = seat
        board_caller = room.get_game_data(viewer=player_name)
        board_caller['message'] = '已向对方提议和棋，等待回应...'
        notify = self._notify_room(room, f'{player_name} 提议和棋', exclude=player_name)

        return {
            'action': 'chess_draw_offer',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board_caller}],
            'send_to_players': notify,
        }

    def _cmd_accept_draw(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room._draw_offer_from is None:
            return self._msg(player_name, '没有和棋提议。')
        seat = room.get_seat(player_name)
        if seat is None or room._draw_offer_from == seat:
            return self._msg(player_name, '不能接受自己的提议。')

        room.accept_draw()
        return self._handle_game_over(lobby, room, player_name, player_data)

    def _cmd_reject_draw(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room._draw_offer_from is None:
            return self._msg(player_name, '没有和棋提议。')
        room._draw_offer_from = None
        board_caller = room.get_game_data(viewer=player_name)
        notify = self._notify_room(room, '和棋提议被拒绝', exclude=player_name)
        return {
            'action': 'chess_draw_rejected',
            'send_to_caller': [
                {'type': GAME, 'text': '已拒绝和棋。'},
                {'type': ROOM_UPDATE, 'room_data': board_caller},
            ],
            'send_to_players': notify,
        }

    # ── 游戏结束 ──

    def _handle_game_over(self, lobby, room, caller, caller_data):
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        result_str = room.result or '1/2-1/2'
        reason = room.result_reason
        summary = f'对局结束: {result_str} ({reason})'

        winner_seat = None
        if result_str == '1-0':
            winner_seat = 0
        elif result_str == '0-1':
            winner_seat = 1

        send_to_players = {}
        refresh_status = []
        has_bots = any(room.is_bot(p) for p in room.players if p)
        rank_changes = {}

        for i, p in enumerate(room.players):
            if not p:
                continue
            pd = None
            if p == caller:
                pd = caller_data
            elif not room.is_bot(p):
                pd = lobby.online_players.get(p)
            if pd is None:
                continue

            if winner_seat is not None:
                if i == winner_seat:
                    exp, gold = self._REWARDS['win']
                    self.report_game_result(lobby, p, pd, 'win')
                    rc = self._update_player_rank(pd, 'win', has_bots)
                else:
                    exp, gold = self._REWARDS['loss']
                    self.report_game_result(lobby, p, pd, 'loss')
                    rc = self._update_player_rank(pd, 'loss', has_bots)
            else:
                exp, gold = self._REWARDS['draw']
                self.report_game_result(lobby, p, pd, 'draw')
                rc = self._update_player_rank(pd, 'draw', has_bots)
            rank_changes[p] = rc

            pd['exp'] = pd.get('exp', 0) + exp
            check_level_up(pd)
            pd['gold'] = max(0, pd.get('gold', 0) + gold)
            PlayerManager.save_player_data(p, pd)
            refresh_status.append(p)

            lobby.set_player_location(p, 'chess_room')
            board = room.get_game_data(viewer=p)
            board['rank_changes'] = rank_changes
            rk = self._format_rank_change(rank_changes.get(p))
            text = summary
            if rk:
                text += f'\n{rk}'
            msgs = [
                {'type': GAME, 'text': text},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'chess_room'},
            ]
            if p == caller:
                caller_msgs = msgs
            else:
                send_to_players[p] = msgs

        # 重置房间
        room.state = 'waiting'
        room.board.reset()
        room.move_history.clear()
        room.result = None
        room.result_reason = ''
        room._draw_offer_from = None

        return {
            'action': 'chess_game_over',
            'send_to_caller': caller_msgs,
            'send_to_players': send_to_players,
            'refresh_commands': True,
            'refresh_status': refresh_status,
        }

    # ── Bot 调度 ──

    def _maybe_schedule_bot(self, room) -> list[dict]:
        """如果轮到 Bot 走，生成调度任务"""
        if room.state != 'playing':
            return []
        current = room.current_player()
        if current and room.is_bot(current):
            difficulty = 'normal'
            if 'easy' in current.lower():
                difficulty = 'easy'
            elif 'hard' in current.lower():
                difficulty = 'hard'
            return [{
                'game_id': 'chess',
                'action': 'bot_move',
                'room_id': room.room_id,
                'difficulty': difficulty,
            }]
        return []


def create_bot_scheduler(server):
    return ChessBotScheduler(server)


class ChessBotScheduler:
    """国际象棋 Bot 调度器 — 使用 Stockfish"""

    def __init__(self, server):
        self._server = server
        self._sf_engine = None

    def _get_stockfish(self):
        if self._sf_engine is None:
            import chess.engine
            from ...config import STOCKFISH_PATH
            try:
                self._sf_engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            except Exception:
                self._sf_engine = None
        return self._sf_engine

    def handle_schedule(self, task):
        import threading
        action = task.get('action')
        if action == 'bot_move':
            rid = task['room_id']
            difficulty = task.get('difficulty', 'normal')
            delay = random.uniform(1.0, 2.5)
            threading.Timer(delay, self._do_bot_move, args=(rid, difficulty)).start()

    def _do_bot_move(self, room_id, difficulty):
        import chess.engine as chess_engine

        server = self._server
        lobby = server.lobby_engine
        engine = lobby.game_engines.get('chess')
        if not engine:
            return
        room = engine._rooms.get(room_id)
        if not room or room.state != 'playing':
            return

        bot_name = room.current_player()
        if not bot_name or not room.is_bot(bot_name):
            return

        # 先尝试 Stockfish
        sf = self._get_stockfish()
        if sf:
            skill = {'easy': 1, 'normal': 10, 'hard': 20}.get(difficulty, 10)
            try:
                sf.configure({'Skill Level': skill})
                time_limit = {'easy': 0.1, 'normal': 0.5, 'hard': 2.0}.get(difficulty, 0.5)
                result = sf.play(room.board, chess_engine.Limit(time=time_limit))
                uci_move = result.move.uci()
            except Exception:
                uci_move = self._random_move(room)
        else:
            uci_move = self._random_move(room)

        if not uci_move:
            return

        # 执行走棋
        move = room.try_move(uci_move)
        if not move:
            return

        # 通知所有真人玩家
        with server.lock:
            for p in room.players:
                if p and not room.is_bot(p):
                    board = room.get_game_data(viewer=p)
                    server.send_to_player(p, {'type': ROOM_UPDATE, 'room_data': board})

            # 游戏结束 → 走结算流程
            if room.state == 'finished':
                for p in room.players:
                    if p and not room.is_bot(p):
                        pd = server._get_player_data(p)
                        if pd:
                            result = engine._handle_game_over(lobby, room, p, pd)
                            from ...core.result_dispatcher import dispatch_game_result
                            dispatch_game_result(server, result, caller_name=p, caller_data=pd)
                            break
            else:
                # 可能又轮到另一个 bot（不太可能但防御性）
                schedules = engine._maybe_schedule_bot(room)
                for task in schedules:
                    self.handle_schedule(task)

    def _random_move(self, room) -> str | None:
        """Fallback: 随机合法走法"""
        moves = list(room.board.legal_moves)
        return random.choice(moves).uci() if moves else None

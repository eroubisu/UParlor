"""德州扑克引擎 — 房间制 2-6 人

位置层级: holdem_lobby → holdem_room → holdem_playing
"""

from __future__ import annotations

import os
import random
import threading

from ...core.protocol import BaseGameEngine
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE
from .room import HoldemRoom, BIG_BLIND

_dir = os.path.dirname(__file__)
_data_dir = os.path.join(_dir, 'data')


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


class HoldemEngine(BaseGameEngine):
    """德州扑克引擎"""

    game_key = 'holdem'
    display_name = '德州扑克'
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
            'fold': '_cmd_fold',
            'call': '_cmd_call',
            'check': '_cmd_check',
            'raise': '_cmd_raise',
            'allin': '_cmd_allin',
            'quit': '_cmd_quit_playing',
        },
    }

    def __init__(self):
        self._init_rooms()

    def get_player_room(self, player_name):
        room_id = self._player_room.get(player_name)
        return self._rooms.get(room_id) if room_id else None

    def get_player_room_data(self, player_name):
        room = self.get_player_room(player_name)
        return room.get_game_data(viewer=player_name) if room else None

    def handle_disconnect(self, lobby, player_name):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            seat = room.get_seat(player_name)
            if seat and not seat.folded:
                room.fold(player_name)
        self._remove_player(player_name)
        return []

    def handle_back(self, lobby, player_name, player_data):
        location = lobby.get_player_location(player_name)
        if location == 'holdem_playing':
            room = self.get_player_room(player_name)
            if room and room.state == 'playing':
                return self._cmd_quit_playing(lobby, player_name, player_data, '')
            return self._cmd_leave(lobby, player_name, player_data, '')
        if location == 'holdem_room':
            return self._cmd_leave(lobby, player_name, player_data, '')
        return self.handle_quit(lobby, player_name, player_data)

    def handle_quit(self, lobby, player_name, player_data):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            seat = room.get_seat(player_name)
            if seat and not seat.folded:
                room.fold(player_name)
        self._remove_player(player_name)
        parent = lobby.get_parent_location(f'{self.game_key}_lobby')
        lobby.set_player_location(player_name, parent)
        return {
            'action': 'location_update',
            'location': parent,
            'send_to_caller': [{'type': GAME, 'text': '离开了德州扑克。'}],
            'refresh_commands': True,
        }

    # ── 辅助 ──

    def _cmd_quit_playing(self, lobby, player_name, player_data, args):
        """游戏中退出 — 带确认"""
        if not args or args.strip() != 'y':
            return self._select_menu('确认退出？你将自动弃牌', [
                {'label': '确认退出', 'command': '/quit y'},
                {'label': '取消', 'command': ''},
            ])
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            seat = room.get_seat(player_name)
            if seat and not seat.folded:
                room.fold(player_name)
            if room.state == 'finished':
                return self._handle_game_over(lobby, room, player_name, player_data)
        return self._cmd_leave(lobby, player_name, player_data, '')

    def _remove_player(self, player_name):
        room = self.get_player_room(player_name)
        if room:
            room.remove_player(player_name)
            room_id = self._player_room.pop(player_name, None)
            active = room.active_players()
            if (not active or all(room.is_bot(p) for p in active)) and room_id:
                self._rooms.pop(room_id, None)
            elif room.host == player_name:
                for p in active:
                    if not room.is_bot(p):
                        room.host = p
                        break

    def _notify_room(self, room, message, exclude=None):
        players = {}
        for p in room.active_players():
            if p == exclude:
                continue
            rd = room.get_game_data(viewer=p)
            msgs = []
            if message:
                msgs.append({'type': GAME, 'text': message})
            msgs.append({'type': ROOM_UPDATE, 'room_data': rd})
            players[p] = msgs
        return players

    # ── 大厅 ──

    def _cmd_create(self, lobby, player_name, player_data, args):
        self._remove_player(player_name)
        room_id = self.gen_room_id()
        while room_id in self._rooms:
            room_id = self.gen_room_id()
        room = HoldemRoom(room_id, player_name)
        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        lobby.set_player_location(player_name, 'holdem_room')
        return {
            'action': 'holdem_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': f'创建了德州扜克房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': 'holdem_room'},
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
                f'  {room.player_count}/{room.MAX_PLAYERS}人'
                f'  {label.get(room.state, room.state)}'
            )
        return self._msg(player_name, '\n'.join(lines))

    def _cmd_accept(self, lobby, player_name, player_data, args):
        import time
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
        lobby.set_player_location(player_name, 'holdem_room')

        td = room.get_table_data()
        notify = self._notify_room(room, f'{player_name} 加入了房间', exclude=player_name)
        return {
            'action': 'holdem_join',
            'send_to_caller': [
                {'type': GAME, 'text': f'加入了房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': td},
                {'type': LOCATION_UPDATE, 'location': 'holdem_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    # ── 房间 ──

    def _cmd_start(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.player_count < 2:
            return self._msg(player_name, '至少需要 2 名玩家。')
        if room.state not in ('waiting', 'finished'):
            return self._msg(player_name, '游戏已在进行中。')

        room.start_hand()
        for p in room.active_players():
            if not room.is_bot(p):
                lobby.set_player_location(p, 'holdem_playing')

        notify = self._notify_room(room, '新一手开始！', exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'holdem_start',
            'send_to_caller': [
                {'type': GAME, 'text': '新一手开始！'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'holdem_playing'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
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
                'game': 'holdem', 'room_id': room.room_id,
                'expires_in': INVITE_EXPIRE,
            })
        return self._msg(player_name, f'已向 {target} 发送邀请。')

    def _cmd_kick(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '只有房主才能踢人。')
        others = [p for p in room.active_players() if p != player_name]
        if not others:
            return self._msg(player_name, '房间里没有其他玩家。')

        if not args or not args.startswith('@'):
            items = [{'label': p, 'command': f'/kick @{p}'} for p in others]
            return self._select_menu('踢出玩家', items)

        target = args[1:].strip()
        if target not in others:
            return self._msg(player_name, f'{target} 不在房间中。')
        room.remove_player(target)
        self._player_room.pop(target, None)
        lobby.set_player_location(target, 'holdem_lobby')
        lobby_board = self._lobby_board()
        from ...lobby.help import get_help_welcome
        lobby_board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
        td = room.get_table_data()
        return {
            'action': 'holdem_kick',
            'send_to_caller': [
                {'type': GAME, 'text': f'已踢出 {target}'},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
            'send_to_players': {
                target: [
                    {'type': GAME, 'text': '你被踢出了房间。'},
                    {'type': ROOM_UPDATE, 'room_data': lobby_board},
                    {'type': LOCATION_UPDATE, 'location': 'holdem_lobby'},
                ],
            },
            'refresh_commands': True,
        }

    def _cmd_leave(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        self._remove_player(player_name)
        lobby.set_player_location(player_name, 'holdem_lobby')
        board = self._lobby_board()
        from ...lobby.help import get_help_welcome
        board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT

        result = {
            'action': 'holdem_leave',
            'send_to_caller': [
                {'type': GAME, 'text': '离开了房间'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'holdem_lobby'},
            ],
            'refresh_commands': True,
        }
        if room:
            others = [p for p in room.active_players() if p != player_name]
            if others:
                td = room.get_table_data()
                result['send_to_players'] = {
                    o: [
                        {'type': GAME, 'text': f'{player_name} 离开了房间'},
                        {'type': ROOM_UPDATE, 'room_data': td},
                    ]
                    for o in others
                }
        return result

    # ── 游戏中 ──

    def _cmd_fold(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.current_player() != player_name:
            return self._msg(player_name, '还没轮到你。')
        room.fold(player_name)
        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)
        return self._broadcast_update(room, player_name)

    def _cmd_call(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.current_player() != player_name:
            return self._msg(player_name, '还没轮到你。')
        if not room.call(player_name):
            return self._msg(player_name, '无法跟注。')
        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)
        return self._broadcast_update(room, player_name)

    def _cmd_check(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.current_player() != player_name:
            return self._msg(player_name, '还没轮到你。')
        if not room.check(player_name):
            return self._msg(player_name, '不能过牌，需要跟注。')
        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)
        return self._broadcast_update(room, player_name)

    def _cmd_raise(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.current_player() != player_name:
            return self._msg(player_name, '还没轮到你。')

        # 子菜单选择加注金额
        if not args:
            seat = room.get_seat(player_name)
            if not seat:
                return self._msg(player_name, '无法加注。')
            min_r = room.current_bet + room.min_raise
            max_r = seat.bet_this_round + seat.chips
            options = []
            for mult in [1, 2, 3, 5]:
                total = room.current_bet + BIG_BLIND * mult
                if min_r <= total <= max_r:
                    options.append({
                        'label': f'加注到 {total}',
                        'desc': f'+{BIG_BLIND * mult}',
                        'command': f'/raise {total}',
                    })
            if max_r > min_r:
                options.append({
                    'label': 'All-in',
                    'desc': str(max_r),
                    'command': f'/allin',
                })
            return self._select_menu('加注', options, '无法加注。')

        try:
            total = int(args.strip())
        except ValueError:
            return self._msg(player_name, '无效的金额。')
        if not room.raise_bet(player_name, total):
            return self._msg(player_name, '加注失败。')
        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)
        return self._broadcast_update(room, player_name)

    def _cmd_allin(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.current_player() != player_name:
            return self._msg(player_name, '还没轮到你。')
        if not room.all_in(player_name):
            return self._msg(player_name, '无法全下。')
        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)
        return self._broadcast_update(room, player_name)

    def _broadcast_update(self, room, caller):
        board = room.get_game_data(viewer=caller)
        notify = self._notify_room(room, '', exclude=caller)
        return {
            'action': 'holdem_update',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    # ── 游戏结束 ──

    def _handle_game_over(self, lobby, room, caller, caller_data):
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        winners = {w['name'] for w in room.winners}
        send_to_players = {}
        caller_msgs = None
        refresh_status = []
        has_bots = bool(room.bots)
        rank_changes = {}

        for p in room.active_players():
            if room.is_bot(p):
                continue
            pd = caller_data if p == caller else lobby.online_players.get(p)
            if pd is None:
                continue

            if p in winners:
                exp, gold = self._REWARDS['win']
                self.report_game_result(lobby, p, pd, 'win')
                rc = self._update_player_rank(pd, 'win', has_bots)
            else:
                seat = room.get_seat(p)
                if seat and seat.folded:
                    exp, gold = self._REWARDS['fold']
                else:
                    exp, gold = self._REWARDS['loss']
                self.report_game_result(lobby, p, pd, 'loss')
                rc = self._update_player_rank(pd, 'loss', has_bots)
            rank_changes[p] = rc

            pd['exp'] = pd.get('exp', 0) + exp
            check_level_up(pd)
            pd['gold'] = max(0, pd.get('gold', 0) + gold)
            PlayerManager.save_player_data(p, pd)
            refresh_status.append(p)

            lobby.set_player_location(p, 'holdem_room')
            board = room.get_game_data(viewer=p)
            board['rank_changes'] = rank_changes
            if len(room.winners) == 1:
                w = room.winners[0]
                summary = f'本手结束 — {w.get("name", "?")} 赢得 {w.get("amount", 0)} ({w.get("hand_name", "")})'
            elif room.winners:
                parts = [f'{w.get("name", "?")} 赢得 {w.get("amount", 0)}' for w in room.winners]
                summary = f'本手结束 — {"、".join(parts)}'
            else:
                summary = '本手结束'
            rk = self._format_rank_change(rank_changes.get(p))
            if rk:
                summary += f'\n{rk}'
            msgs = [
                {'type': GAME, 'text': summary},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'holdem_room'},
            ]
            if p == caller:
                caller_msgs = msgs
            else:
                send_to_players[p] = msgs

        # 重置到等待 (保留筹码)
        room.state = 'waiting'

        return {
            'action': 'holdem_game_over',
            'send_to_caller': caller_msgs or [],
            'send_to_players': send_to_players,
            'refresh_commands': True,
            'refresh_status': refresh_status,
        }

    # ── Bot ──

    def _cmd_bot(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.is_full():
            return self._msg(player_name, '房间已满。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始。')

        empty = sum(1 for s in room.seats if s is None)
        if not args:
            items = [{'label': f'添加 {n} 个机器人', 'command': f'/bot {n}'}
                     for n in range(1, empty + 1)]
            return self._select_menu('添加机器人', items)

        count = max(1, min(empty, int(args.strip()) if args.strip().isdigit() else 1))
        added = []
        for _ in range(count):
            ok, name = room.add_bot()
            if ok:
                added.append(name)
            else:
                break

        if not added:
            return self._msg(player_name, '无法添加机器人。')

        names = ', '.join(added)
        td = room.get_table_data()
        return {
            'action': 'holdem_bot_added',
            'send_to_caller': [
                {'type': GAME, 'text': f'已添加机器人: {names}'},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
        }

    def _maybe_schedule_bot(self, room) -> list[dict]:
        if room.state != 'playing':
            return []
        current = room.current_player()
        if current and room.is_bot(current):
            return [{
                'game_id': 'holdem',
                'action': 'bot_turn',
                'room_id': room.room_id,
            }]
        return []


class HoldemBotScheduler:
    """德州扑克 Bot 调度器 — 简单手牌强度策略"""

    from ...config import BOT_DELAY

    def __init__(self, server):
        self._server = server

    def handle_schedule(self, task):
        if task.get('action') == 'bot_turn':
            room_id = task['room_id']
            delay = random.uniform(1.0, 2.5)
            t = threading.Timer(delay, self._run_bot_turn, args=(room_id,))
            t.daemon = True
            t.start()

    def _run_bot_turn(self, room_id):
        server = self._server
        lobby = server.lobby_engine
        engine = lobby.game_engines.get('holdem')
        if not engine:
            return
        room = engine._rooms.get(room_id)
        if not room or room.state != 'playing':
            return

        bot_name = room.current_player()
        if not bot_name or not room.is_bot(bot_name):
            return

        seat = room.get_seat(bot_name)
        if not seat or seat.folded or seat.all_in:
            return

        action = self._decide(room, seat)
        if action == 'fold':
            room.fold(bot_name)
        elif action == 'call':
            room.call(bot_name)
        elif action == 'check':
            room.check(bot_name)
        elif action == 'allin':
            room.all_in(bot_name)
        else:  # raise
            total = room.current_bet + room.min_raise
            if not room.raise_bet(bot_name, total):
                room.call(bot_name) or room.check(bot_name)

        with server.lock:
            for p in room.active_players():
                if not room.is_bot(p):
                    board = room.get_game_data(viewer=p)
                    server.send_to_player(p, {'type': ROOM_UPDATE, 'room_data': board})

            if room.state == 'finished':
                for p in room.active_players():
                    if not room.is_bot(p):
                        pd = server._get_player_data(p)
                        if pd:
                            from ...core.result_dispatcher import dispatch_game_result
                            result = engine._handle_game_over(lobby, room, p, pd)
                            dispatch_game_result(server, result, caller_name=p, caller_data=pd)
                            break
            else:
                for t in engine._maybe_schedule_bot(room):
                    self.handle_schedule(t)

    @staticmethod
    def _hand_strength(hand_cards) -> int:
        """简单手牌评估 (preflop): 0=弱, 1=中, 2=强"""
        if len(hand_cards) < 2:
            return 0
        r1 = hand_cards[0].rank
        r2 = hand_cards[1].rank
        paired = r1 == r2
        hi = max(r1, r2)
        if paired:
            return 2 if hi >= 10 else 1
        if hi >= 13:
            return 2 if min(r1, r2) >= 10 else 1
        return 0

    def _decide(self, room, seat) -> str:
        to_call = room.current_bet - seat.bet_this_round
        strength = self._hand_strength(seat.hand)
        has_community = len(room.community) > 0

        if to_call == 0:
            # 无需跟注
            if strength >= 2:
                return 'raise' if random.random() < 0.4 else 'check'
            return 'check'

        # 需要跟注
        pot_odds = to_call / max(room.pot, 1)
        if strength >= 2:
            return 'raise' if pot_odds < 0.3 and random.random() < 0.3 else 'call'
        if strength == 1:
            return 'call' if pot_odds < 0.5 else 'fold'
        # 弱牌
        if has_community and pot_odds < 0.2:
            return 'call'
        return 'fold'


def create_bot_scheduler(server):
    return HoldemBotScheduler(server)

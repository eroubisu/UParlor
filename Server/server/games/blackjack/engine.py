"""21点游戏引擎 — 房间制，2-6 人 vs 庄家(NPC)

位置层级: blackjack_lobby → blackjack_room → blackjack_playing
"""

from __future__ import annotations

import os
import random
import threading

from ...core.protocol import BaseGameEngine
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE
from .room import BlackjackRoom

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


class BlackjackEngine(BaseGameEngine):
    """21点引擎 — 房间制"""

    game_key = 'blackjack'
    display_name = '21点'
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
            'hit': '_cmd_hit',
            'stand': '_cmd_stand',
            'double': '_cmd_double',
            'quit': '_cmd_quit_playing',
        },
    }

    def __init__(self):
        self._init_rooms()

    def get_player_room(self, player_name: str) -> BlackjackRoom | None:
        room_id = self._player_room.get(player_name)
        return self._rooms.get(room_id) if room_id else None

    def get_player_room_data(self, player_name: str) -> dict | None:
        room = self.get_player_room(player_name)
        return room.get_game_data(viewer=player_name) if room else None

    def handle_disconnect(self, lobby, player_name):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            hand = room.hands.get(player_name)
            if hand and not hand.stood and not hand.busted:
                room.stand(player_name)
                if room.state == 'finished':
                    return self._broadcast_game_over(lobby, room, player_name)
        self._remove_player(player_name)
        return []

    def handle_back(self, lobby, player_name, player_data):
        location = lobby.get_player_location(player_name)
        if location == 'blackjack_playing':
            room = self.get_player_room(player_name)
            if room and room.state == 'playing':
                return self._cmd_quit_playing(lobby, player_name, player_data, '')
            return self._cmd_leave(lobby, player_name, player_data, '')
        if location == 'blackjack_room':
            return self._cmd_leave(lobby, player_name, player_data, '')
        return self.handle_quit(lobby, player_name, player_data)

    def handle_quit(self, lobby, player_name, player_data):
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            hand = room.hands.get(player_name)
            if hand and not hand.stood and not hand.busted:
                room.stand(player_name)
        self._remove_player(player_name)
        parent = lobby.get_parent_location(f'{self.game_key}_lobby')
        lobby.set_player_location(player_name, parent)
        return {
            'action': 'location_update',
            'location': parent,
            'send_to_caller': [{'type': GAME, 'text': '离开了21点。'}],
            'refresh_commands': True,
        }

    # ── 辅助 ──

    def _cmd_quit_playing(self, lobby, player_name, player_data, args):
        """游戏中退出 — 带确认"""
        if not args or args.strip() != 'y':
            return self._select_menu('确认退出？你将自动停牌', [
                {'label': '确认退出', 'command': '/quit y'},
                {'label': '取消', 'command': ''},
            ])
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            hand = room.hands.get(player_name)
            if hand and not hand.stood and not hand.busted:
                room.stand(player_name)
            if room.state == 'finished':
                return self._handle_game_over(lobby, room, player_name, player_data)
        return self._cmd_leave(lobby, player_name, player_data, '')

    def _remove_player(self, player_name: str):
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
        """通知房间内所有玩家"""
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
        room = BlackjackRoom(room_id, player_name)
        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        lobby.set_player_location(player_name, 'blackjack_room')
        return {
            'action': 'blackjack_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': f'创建了21点房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': 'blackjack_room'},
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
        lobby.set_player_location(player_name, 'blackjack_room')

        td = room.get_table_data()
        notify = self._notify_room(room, f'{player_name} 加入了房间', exclude=player_name)
        return {
            'action': 'blackjack_join',
            'send_to_caller': [
                {'type': GAME, 'text': f'加入了房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': td},
                {'type': LOCATION_UPDATE, 'location': 'blackjack_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    # ── 房间 ──

    def _cmd_start(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.player_count < 1:
            return self._msg(player_name, '至少需要 1 名玩家。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已在进行中。')

        room.start()
        for p in room.active_players():
            if not room.is_bot(p):
                lobby.set_player_location(p, 'blackjack_playing')

        notify = self._notify_room(room, '21点开始！', exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'blackjack_start',
            'send_to_caller': [
                {'type': GAME, 'text': '21点开始！'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'blackjack_playing'},
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
                'game': 'blackjack', 'room_id': room.room_id,
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
        lobby.set_player_location(target, 'blackjack_lobby')
        lobby_board = self._lobby_board()
        from ...lobby.help import get_help_welcome
        lobby_board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
        td = room.get_table_data()
        return {
            'action': 'blackjack_kick',
            'send_to_caller': [
                {'type': GAME, 'text': f'已踢出 {target}'},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
            'send_to_players': {
                target: [
                    {'type': GAME, 'text': '你被踢出了房间。'},
                    {'type': ROOM_UPDATE, 'room_data': lobby_board},
                    {'type': LOCATION_UPDATE, 'location': 'blackjack_lobby'},
                ],
            },
            'refresh_commands': True,
        }

    def _cmd_leave(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        self._remove_player(player_name)
        lobby.set_player_location(player_name, 'blackjack_lobby')
        board = self._lobby_board()
        from ...lobby.help import get_help_welcome
        board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT

        result = {
            'action': 'blackjack_leave',
            'send_to_caller': [
                {'type': GAME, 'text': '离开了房间'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'blackjack_lobby'},
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
                    ] for o in others
                }
        return result

    # ── 游戏中 ──

    def _cmd_hit(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.current_player() != player_name:
            return self._msg(player_name, '还没轮到你。')

        if not room.hit(player_name):
            return self._msg(player_name, '无法要牌。')

        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)

        board = room.get_game_data(viewer=player_name)
        notify = self._notify_room(room, '', exclude=player_name)
        return {
            'action': 'blackjack_hit',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _cmd_stand(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.current_player() != player_name:
            return self._msg(player_name, '还没轮到你。')

        if not room.stand(player_name):
            return self._msg(player_name, '无法停牌。')

        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)

        board = room.get_game_data(viewer=player_name)
        notify = self._notify_room(room, '', exclude=player_name)
        return {
            'action': 'blackjack_stand',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _cmd_double(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.current_player() != player_name:
            return self._msg(player_name, '还没轮到你。')

        hand = room.hands.get(player_name)
        if not hand or len(hand.cards) != 2:
            return self._msg(player_name, '只能在前两张牌时加倍。')

        if not room.double_down(player_name):
            return self._msg(player_name, '无法加倍。')

        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)

        board = room.get_game_data(viewer=player_name)
        notify = self._notify_room(room, '', exclude=player_name)
        return {
            'action': 'blackjack_double',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    # ── 游戏结束 ──

    def _handle_game_over(self, lobby, room, caller, caller_data):
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        results = room.get_results()
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

            r = results.get(p, {})
            outcome = r.get('outcome', 'lose')
            if outcome in ('win', 'blackjack'):
                exp, gold = self._REWARDS['win']
                self.report_game_result(lobby, p, pd, 'win')
                rc = self._update_player_rank(pd, 'win', has_bots)
            elif outcome == 'push':
                exp, gold = self._REWARDS['push']
                self.report_game_result(lobby, p, pd, 'draw')
                rc = self._update_player_rank(pd, 'draw', has_bots)
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

            lobby.set_player_location(p, 'blackjack_room')
            board = room.get_game_data(viewer=p)
            board['rank_changes'] = rank_changes
            result_text = self._format_result(p, results)
            rk = self._format_rank_change(rank_changes.get(p))
            if rk:
                result_text += f'\n{rk}'
            msgs = [
                {'type': GAME, 'text': result_text},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'blackjack_room'},
            ]
            if p == caller:
                caller_msgs = msgs
            else:
                send_to_players[p] = msgs

        # 重置房间
        room.state = 'waiting'
        room.hands.clear()
        room.dealer_cards.clear()

        return {
            'action': 'blackjack_game_over',
            'send_to_caller': caller_msgs or [],
            'send_to_players': send_to_players,
            'refresh_commands': True,
            'refresh_status': refresh_status,
        }

    def _broadcast_game_over(self, lobby, room, disconnected):
        """断线时触发的结算（返回消息列表给其他玩家）"""
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        results = room.get_results()
        has_bots = bool(room.bots)
        notify = []
        for p in room.active_players():
            if p == disconnected or room.is_bot(p):
                continue
            pd = lobby.online_players.get(p)
            if not pd:
                continue

            r = results.get(p, {})
            outcome = r.get('outcome', 'lose')
            if outcome in ('win', 'blackjack'):
                exp, gold = self._REWARDS['win']
                self.report_game_result(lobby, p, pd, 'win')
                rc = self._update_player_rank(pd, 'win', has_bots)
            elif outcome == 'push':
                exp, gold = self._REWARDS['push']
                self.report_game_result(lobby, p, pd, 'draw')
                rc = self._update_player_rank(pd, 'draw', has_bots)
            else:
                exp, gold = self._REWARDS['loss']
                self.report_game_result(lobby, p, pd, 'loss')
                rc = self._update_player_rank(pd, 'loss', has_bots)

            pd['exp'] = pd.get('exp', 0) + exp
            check_level_up(pd)
            pd['gold'] = max(0, pd.get('gold', 0) + gold)
            PlayerManager.save_player_data(p, pd)

            result_text = self._format_result(p, results)
            rk = self._format_rank_change(rc)
            if rk:
                result_text += f'\n{rk}'

            board = room.get_game_data(viewer=p)
            notify.append({
                'target': p,
                'messages': [
                    {'type': GAME, 'text': result_text},
                    {'type': ROOM_UPDATE, 'room_data': board},
                ],
            })
        room.state = 'waiting'
        room.hands.clear()
        room.dealer_cards.clear()
        return notify

    def _format_result(self, player_name: str, results: dict) -> str:
        r = results.get(player_name, {})
        outcome = r.get('outcome', '?')
        payout = r.get('payout', 0)
        val = r.get('value', 0)
        labels = {
            'win': '赢了', 'blackjack': 'Blackjack!',
            'push': '平局', 'lose': '输了',
        }
        sign = '+' if payout >= 0 else ''
        return f'21点结束 — {labels.get(outcome, outcome)} ({val}点, {sign}{payout}筹码)'

    # ── Bot ──

    def _cmd_bot(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始。')

        empty = sum(1 for p in room.players if p is None)
        if empty == 0:
            return self._msg(player_name, '房间已满。')

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
            'action': 'blackjack_bot_added',
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
                'game_id': 'blackjack',
                'action': 'bot_turn',
                'room_id': room.room_id,
            }]
        return []


class BlackjackBotScheduler:
    """21点 Bot 调度器 — 基本策略 AI"""

    from ...config import BOT_DELAY

    def __init__(self, server):
        self._server = server

    def handle_schedule(self, task):
        if task.get('action') == 'bot_turn':
            room_id = task['room_id']
            delay = random.uniform(1.0, 2.0)
            t = threading.Timer(delay, self._run_bot_turn, args=(room_id,))
            t.daemon = True
            t.start()

    def _run_bot_turn(self, room_id):
        server = self._server
        lobby = server.lobby_engine
        engine = lobby.game_engines.get('blackjack')
        if not engine:
            return
        room = engine._rooms.get(room_id)
        if not room or room.state != 'playing':
            return

        bot_name = room.current_player()
        if not bot_name or not room.is_bot(bot_name):
            return

        hand = room.hands.get(bot_name)
        if not hand or hand.stood or hand.busted:
            return

        action = self._decide(hand)
        if action == 'double':
            room.double_down(bot_name)
        elif action == 'hit':
            room.hit(bot_name)
        else:
            room.stand(bot_name)

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
    def _decide(hand) -> str:
        value = hand.value
        is_soft = hand.is_soft
        if len(hand.cards) == 2 and not is_soft and value in (10, 11):
            return 'double'
        if is_soft:
            return 'hit' if value <= 17 else 'stand'
        return 'hit' if value < 17 else 'stand'


def create_bot_scheduler(server):
    return BlackjackBotScheduler(server)

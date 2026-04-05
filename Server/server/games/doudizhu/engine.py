"""斗地主引擎 — 3 人房间制

位置层级: doudizhu_lobby → doudizhu_room → doudizhu_playing
"""

from __future__ import annotations

import os
import random
import threading

from ...core.protocol import BaseGameEngine
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE
from .room import DoudizhuRoom

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


class DoudizhuEngine(BaseGameEngine):
    """斗地主引擎 — 3 人房间制"""

    game_key = 'doudizhu'
    display_name = '斗地主'
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
            'bid': '_cmd_bid',
            'play': '_cmd_play',
            'pass': '_cmd_pass',
        },
    }

    def __init__(self):
        self._init_rooms()

    # ── Protocol ──

    def get_player_room(self, player_name: str) -> DoudizhuRoom | None:
        room_id = self._player_room.get(player_name)
        return self._rooms.get(room_id) if room_id else None

    def get_player_room_data(self, player_name: str) -> dict | None:
        room = self.get_player_room(player_name)
        return room.get_game_data(viewer=player_name) if room else None

    def handle_disconnect(self, lobby, player_name):
        room = self.get_player_room(player_name)
        if room and room.state in ('bidding', 'playing'):
            room.state = 'finished'
            room.winner = ''
            notify = []
            for p in room.players:
                if p == player_name or room.is_bot(p):
                    continue
                pd = lobby.online_players.get(p)
                if not pd:
                    continue
                lobby.set_player_location(p, 'doudizhu_room')
                board = room.get_game_data(viewer=p)
                board['message'] = f'{player_name} 断线了，游戏结束。'
                notify.append({
                    'target': p,
                    'messages': [
                        {'type': GAME, 'text': f'{player_name} 断线了。'},
                        {'type': ROOM_UPDATE, 'room_data': board},
                        {'type': LOCATION_UPDATE, 'location': 'doudizhu_room'},
                    ],
                })
            self._cleanup_room(room)
            return notify
        self._remove_player(player_name)
        return []

    def handle_back(self, lobby, player_name, player_data):
        location = lobby.get_player_location(player_name)
        if location == 'doudizhu_playing':
            return self._msg(player_name, '游戏进行中，不能离开。')
        if location == 'doudizhu_room':
            return self._cmd_leave(lobby, player_name, player_data, '')
        return self.handle_quit(lobby, player_name, player_data)

    def handle_quit(self, lobby, player_name, player_data):
        room = self.get_player_room(player_name)
        if room and room.state in ('bidding', 'playing'):
            return self._msg(player_name, '游戏进行中，不能离开。')
        self._remove_player(player_name)
        parent = lobby.get_parent_location(f'{self.game_key}_lobby')
        lobby.set_player_location(player_name, parent)
        return {
            'action': 'location_update',
            'location': parent,
            'send_to_caller': [{'type': GAME, 'text': '离开了斗地主。'}],
            'refresh_commands': True,
        }

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

    def _cleanup_room(self, room: DoudizhuRoom):
        """清理已结束的房间"""
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

    # ── 大厅 ──

    def _cmd_create(self, lobby, player_name, player_data, args):
        self._remove_player(player_name)
        room_id = self.gen_room_id()
        while room_id in self._rooms:
            room_id = self.gen_room_id()
        room = DoudizhuRoom(room_id, [player_name])
        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        lobby.set_player_location(player_name, 'doudizhu_room')
        return {
            'action': 'doudizhu_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': f'创建了斗地主房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': 'doudizhu_room'},
            ],
            'refresh_commands': True,
        }

    def _cmd_rooms(self, lobby, player_name, player_data, args):
        if not self._rooms:
            return self._msg(player_name, '暂无房间。')
        lines = ['当前房间:']
        for room in self._rooms.values():
            label = {'waiting': '等待中', 'bidding': '叫分中',
                     'playing': '进行中', 'finished': '已结束'}
            lines.append(
                f'  #{room.room_id}  {room.host}'
                f'  {len(room.players)}/{room.PLAYERS_NEEDED}人'
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
        if not room or room.state != 'waiting':
            return self._msg(player_name, '房间已不可用。')
        if len(room.players) >= room.PLAYERS_NEEDED:
            return self._msg(player_name, '房间已满。')

        self._remove_player(player_name)
        room.players.append(player_name)
        room.hands[player_name] = None  # placeholder
        self._player_room[player_name] = room_id
        lobby.set_player_location(player_name, 'doudizhu_room')

        td = room.get_table_data()
        notify = self._notify_room(room, f'{player_name} 加入了房间', exclude=player_name)
        return {
            'action': 'doudizhu_join',
            'send_to_caller': [
                {'type': GAME, 'text': f'加入了房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': td},
                {'type': LOCATION_UPDATE, 'location': 'doudizhu_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    # ── 房间 ──

    def _cmd_start(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if len(room.players) < room.PLAYERS_NEEDED:
            return self._msg(player_name, f'需要 {room.PLAYERS_NEEDED} 名玩家。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已在进行中。')

        room.start()
        for p in room.players:
            if not room.is_bot(p):
                lobby.set_player_location(p, 'doudizhu_playing')

        notify = self._notify_room(room, '斗地主开始！叫分阶段。',
                                   exclude=player_name,
                                   location='doudizhu_playing')
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'doudizhu_start',
            'send_to_caller': [
                {'type': GAME, 'text': '斗地主开始！叫分阶段。'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'doudizhu_playing'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _cmd_invite(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你不在房间中。')
        if len(room.players) >= room.PLAYERS_NEEDED:
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
                'game': 'doudizhu', 'room_id': room.room_id,
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
        self._player_room.pop(target, None)
        lobby.set_player_location(target, 'doudizhu_lobby')
        lobby_board = self._lobby_board()
        from ...lobby.help import get_help_welcome
        lobby_board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
        td = room.get_table_data()
        return {
            'action': 'doudizhu_kicked',
            'send_to_caller': [
                {'type': GAME, 'text': f'已踢出 {target}'},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
            'send_to_players': {
                target: [
                    {'type': GAME, 'text': f'你被踢出了房间。'},
                    {'type': ROOM_UPDATE, 'room_data': lobby_board},
                    {'type': LOCATION_UPDATE, 'location': 'doudizhu_lobby'},
                ],
            },
            'refresh_commands': True,
        }

    def _cmd_leave(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if room and room.state in ('bidding', 'playing'):
            return self._msg(player_name, '游戏进行中，不能离开。')

        self._remove_player(player_name)
        lobby.set_player_location(player_name, 'doudizhu_lobby')
        lobby_board = self._lobby_board()
        from ...lobby.help import get_help_welcome
        lobby_board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
        result = {
            'action': 'doudizhu_leave',
            'send_to_caller': [
                {'type': GAME, 'text': '离开了房间。'},
                {'type': ROOM_UPDATE, 'room_data': lobby_board},
                {'type': LOCATION_UPDATE, 'location': 'doudizhu_lobby'},
            ],
            'refresh_commands': True,
        }
        if room and room.players:
            result['send_to_players'] = self._notify_room(
                room, f'{player_name} 离开了房间')
        return result

    # ── 游戏中: 叫分 ──

    def _cmd_bid(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'bidding':
            return self._msg(player_name, '当前不在叫分阶段。')

        if not args:
            # 弹出叫分子菜单
            items = [
                {'label': '不叫 (0分)', 'command': '/bid 0'},
                {'label': '1 分', 'command': '/bid 1'},
                {'label': '2 分', 'command': '/bid 2'},
                {'label': '3 分', 'command': '/bid 3'},
            ]
            return self._select_menu('叫分', items)

        try:
            score = int(args.strip())
        except ValueError:
            return self._msg(player_name, '无效的分数。')

        if score not in (0, 1, 2, 3):
            return self._msg(player_name, '分数必须是 0/1/2/3。')

        result_msg = room.bid(player_name, score)
        if result_msg is None:
            return self._msg(player_name, '不是你的回合。')

        # 叫分结果 — 确定地主或无人叫分时写入记录
        resolved = room.state == 'playing' or '无人叫分' in result_msg
        bid_chat = result_msg if resolved else None
        notify = self._notify_room(room, bid_chat, exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        caller_msgs = []
        if bid_chat:
            caller_msgs.append({'type': GAME, 'text': bid_chat})
        caller_msgs.append({'type': ROOM_UPDATE, 'room_data': board})
        response = {
            'action': 'doudizhu_bid',
            'send_to_caller': caller_msgs,
            'send_to_players': notify,
        }

        # 如果进入 playing 阶段，刷新指令
        if room.state == 'playing':
            response['refresh_commands'] = True

        response['schedule'] = self._maybe_schedule_bot(room)
        return response

    # ── 游戏中: 出牌 ──

    def _cmd_play(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在出牌阶段。')

        if not args:
            return self._msg(player_name, '请输入牌序号。')

        # 'p' / 'pass' = 不出
        if args.strip().lower() in ('p', 'pass'):
            return self._cmd_pass(lobby, player_name, player_data, args)

        # 解析牌索引
        try:
            indices = [int(x) for x in args.strip().split()]
        except ValueError:
            return self._msg(player_name, '无效的牌序号。')

        # 推荐出牌快捷选择: 单个数字 >= 手牌数 → 查推荐表
        from .patterns import PASS
        hand = room.hands[player_name].cards
        if (len(indices) == 1 and indices[0] >= len(hand)
                and room.last_play and room.last_play.type_id != PASS):
            from .patterns import find_all_beats
            suggestions = find_all_beats(hand, room.last_play)
            sug_idx = indices[0] - len(hand)
            if sug_idx < 0 or sug_idx >= len(suggestions):
                return self._msg(player_name, '无效的推荐序号。')
            sug = suggestions[sug_idx]
            if sug.get('type') == 'pass':
                return self._cmd_pass(lobby, player_name, player_data, args)
            if sug.get('type') == 'single_hint':
                return self._msg(player_name, '请直接输入手牌序号。')
            indices = sug['indices']

        ok, msg = room.play_cards(player_name, indices)
        if not ok:
            return self._msg(player_name, msg)

        # 出牌成功 — 只通过 ROOM_UPDATE 同步面板，不刷聊天记录
        notify = self._notify_room(room, None, exclude=player_name)
        board = room.get_game_data(viewer=player_name)

        if room.state == 'finished':
            return self._handle_game_over(lobby, room, player_name, player_data)

        # 炸弹/火箭/出完 等重要事件才广播文本
        from .patterns import BOMB, ROCKET
        important = room.last_play and room.last_play.type_id in (BOMB, ROCKET)
        caller_msgs: list[dict] = []
        if important:
            caller_msgs.append({'type': GAME, 'text': msg})
            notify = self._notify_room(room, msg, exclude=player_name)
        caller_msgs.append({'type': ROOM_UPDATE, 'room_data': board})

        return {
            'action': 'doudizhu_play',
            'send_to_caller': caller_msgs,
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    def _cmd_pass(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '当前不在出牌阶段。')

        ok, msg = room.play_cards(player_name, [])
        if not ok:
            return self._msg(player_name, msg)

        notify = self._notify_room(room, None, exclude=player_name)
        board = room.get_game_data(viewer=player_name)
        return {
            'action': 'doudizhu_pass',
            'send_to_caller': [
                {'type': ROOM_UPDATE, 'room_data': board},
            ],
            'send_to_players': notify,
            'schedule': self._maybe_schedule_bot(room),
        }

    # ── 结算 ──

    def _handle_game_over(self, lobby, room, caller, caller_data):
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        results = room.get_results()
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

            outcome = results.get(p, 'loss')
            if outcome == 'win':
                exp, gold = self._REWARDS['win']
                self.report_game_result(lobby, p, pd, 'win')
                rc = self._update_player_rank(
                    pd, 'win', has_bots, room.multiplier)
            else:
                exp, gold = self._REWARDS['loss']
                self.report_game_result(lobby, p, pd, 'loss')
                rc = self._update_player_rank(
                    pd, 'loss', has_bots, room.multiplier)
            rank_changes[p] = rc

            # Bot 局按单人比例重算金币
            if has_bots:
                gold = int(exp * self._REWARDS.get('gold_ratio_bot', 0.15))

            # 倍率加成
            exp = int(exp * room.multiplier)
            gold = int(gold * room.multiplier)

            pd['exp'] = pd.get('exp', 0) + exp
            check_level_up(pd)
            pd['gold'] = max(0, pd.get('gold', 0) + gold)
            PlayerManager.save_player_data(p, pd)
            refresh_status.append(p)

            lobby.set_player_location(p, 'doudizhu_room')
            board = room.get_game_data(viewer=p)
            board['rank_changes'] = rank_changes
            result_text = self._format_result(
                p, room, exp, gold, rank_changes.get(p),
            )
            msgs = [
                {'type': GAME, 'text': result_text},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'doudizhu_room'},
            ]
            if p == caller:
                caller_msgs = msgs
            else:
                send_to_players[p] = msgs

        # 重置房间
        room.state = 'waiting'
        room.hands.clear()

        return {
            'action': 'doudizhu_game_over',
            'send_to_caller': caller_msgs or [],
            'send_to_players': send_to_players,
            'refresh_commands': True,
            'refresh_status': refresh_status,
        }

    def _format_result(
        self, player: str, room: DoudizhuRoom,
        exp: int, gold: int, rc: dict | None,
    ) -> str:
        results = room.get_results()
        # 只列出胜者
        winners = [p for p in room.players if results.get(p) == 'win']
        lines = []
        for p in winners:
            role = '地主' if p == room.dizhu else '农民'
            lines.append(f'★ {p} ({role}) 胜利')
        header = f'倍率 ×{room.multiplier}'
        if room.spring:
            header += '  春天'
        lines.append(header)
        # 本人奖励
        gold_sign = '+' if gold >= 0 else ''
        lines.append(f'经验 +{exp}  金币 {gold_sign}{gold}')
        # 段位变化
        if rc and rc['delta'] != 0:
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

    def _cmd_bot(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已开始。')

        empty = room.PLAYERS_NEEDED - len(room.players)
        if empty <= 0:
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
            'action': 'doudizhu_bot_added',
            'send_to_caller': [
                {'type': GAME, 'text': f'已添加机器人: {names}'},
                {'type': ROOM_UPDATE, 'room_data': td},
            ],
        }

    def _maybe_schedule_bot(self, room) -> list[dict]:
        if room.state not in ('bidding', 'playing'):
            return []
        current = room.current_player()
        if current and room.is_bot(current):
            return [{
                'game_id': 'doudizhu',
                'action': 'bot_bid' if room.state == 'bidding' else 'bot_play',
                'room_id': room.room_id,
            }]
        return []


class DoudizhuBotScheduler:
    """斗地主 Bot 调度器"""

    from ...config import BOT_DELAY

    def __init__(self, server):
        self._server = server

    def handle_schedule(self, task):
        action = task.get('action')
        room_id = task.get('room_id', '')
        if action in ('bot_bid', 'bot_play'):
            delay = random.uniform(1.0, 2.0)
            t = threading.Timer(delay, self._run_bot_turn, args=(room_id,))
            t.daemon = True
            t.start()

    def _run_bot_turn(self, room_id):
        server = self._server
        lobby = server.lobby_engine
        engine = lobby.game_engines.get('doudizhu')
        if not engine:
            return
        room = engine._rooms.get(room_id)
        if not room or room.state not in ('bidding', 'playing'):
            return

        bot_name = room.current_player()
        if not bot_name or not room.is_bot(bot_name):
            return

        if room.state == 'bidding':
            self._do_bid(engine, lobby, room, bot_name)
        else:
            self._do_play(engine, lobby, room, bot_name)

    def _do_bid(self, engine, lobby, room, bot_name):
        from .patterns import doudizhu_rank, BOMB, ROCKET
        from collections import Counter
        # 简单策略: 根据手牌中炸弹/火箭数量决定叫分
        hand = room.hands.get(bot_name)
        score = 0
        if hand and hand.cards:
            ranks = [doudizhu_rank(c) for c in hand.cards]
            cnt = Counter(ranks)
            bombs = sum(1 for c in cnt.values() if c >= 4)
            has_rocket = 16 in cnt and 17 in cnt
            power = bombs + (1 if has_rocket else 0)
            if power >= 2:
                score = 3
            elif power == 1:
                score = 2
            else:
                # 有大量大牌也叫分
                big_cards = sum(1 for r in ranks if r >= 14)
                score = 1 if big_cards >= 4 else 0

        result_msg = room.bid(bot_name, score)
        if result_msg is None:
            return

        # 确定地主或无人叫分时广播叫分结果到记录
        resolved = room.state == 'playing' or '无人叫分' in result_msg
        bid_chat = result_msg if resolved else None
        self._broadcast(engine, room, bid_chat)

    def _do_play(self, engine, lobby, room, bot_name):
        from .patterns import (
            identify, doudizhu_rank, find_all_beats, sort_hand,
            PASS, BOMB, ROCKET, SINGLE, PAIR, TRIPLE,
            TRIPLE_1, TRIPLE_2, STRAIGHT, STRAIGHT_PAIR,
        )
        from collections import Counter

        hand = room.hands.get(bot_name)
        if not hand or not hand.cards:
            return

        cards = hand.cards
        is_leading = not room.last_play or room.last_player == bot_name

        if is_leading:
            indices = self._bot_lead(cards)
        else:
            # 跟牌: 用 find_all_beats 找最小可出
            suggestions = find_all_beats(cards, room.last_play)
            # 过滤掉 pass
            plays = [s for s in suggestions if s.get('type') != 'pass']
            if plays:
                # 选最小的出法 (find_all_beats 已按 rank 升序)
                indices = plays[0]['indices']
            else:
                indices = []  # pass

        ok, msg = room.play_cards(bot_name, indices)
        if not ok:
            ok, msg = room.play_cards(bot_name, [])
            if not ok:
                return

        important = room.last_play and room.last_play.type_id in (BOMB, ROCKET)
        self._broadcast(engine, room, msg if important else None)

    @staticmethod
    def _bot_lead(cards) -> list[int]:
        """Bot 主动出牌策略: 优先出连牌 > 三带 > 对子 > 单张 (从小到大)"""
        from .patterns import (
            identify, doudizhu_rank,
            SINGLE, PAIR, TRIPLE, TRIPLE_1, TRIPLE_2,
            STRAIGHT, STRAIGHT_PAIR, PLANE, BOMB, ROCKET,
        )
        from collections import Counter

        n = len(cards)
        ranks = [doudizhu_rank(c) for c in cards]
        cnt = Counter(ranks)

        # rank → indices 映射
        rmap: dict[int, list[int]] = {}
        for i, r in enumerate(ranks):
            rmap.setdefault(r, []).append(i)

        # 尝试顺子 (5+ 连续)
        sorted_ranks = sorted(set(r for r in cnt if r <= 14))
        best_seq = _find_longest_run(sorted_ranks, 5)
        if best_seq:
            return [rmap[r][0] for r in best_seq]

        # 尝试连对 (3+ 对连续)
        pair_ranks = sorted(r for r in cnt if cnt[r] >= 2 and r <= 14)
        best_pair_seq = _find_longest_run(pair_ranks, 3)
        if best_pair_seq:
            idxs = []
            for r in best_pair_seq:
                idxs.extend(rmap[r][:2])
            return idxs

        # 三带一/三带二 (从小到大)
        for r in sorted(rmap):
            if cnt[r] >= 3 and r <= 15:
                tri = rmap[r][:3]
                # 带最小的单张
                for r2 in sorted(rmap):
                    if r2 != r:
                        return tri + [rmap[r2][0]]
                return tri

        # 对子 (最小)
        for r in sorted(rmap):
            if cnt[r] >= 2 and r <= 15:
                return rmap[r][:2]

        # 单张 (最小，但避免拆炸弹)
        for r in sorted(rmap):
            if cnt[r] < 4:
                return [rmap[r][0]]

        # 实在没办法就出最小
        return [0]

    def _broadcast(self, engine, room, msg):
        """广播更新给所有真人玩家并处理后续"""
        server = self._server
        lobby = server.lobby_engine

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
                            result = engine._handle_game_over(lobby, room, p, pd)
                            dispatch_game_result(server, result, caller_name=p, caller_data=pd)
                            break
            else:
                for t in engine._maybe_schedule_bot(room):
                    self.handle_schedule(t)


def create_bot_scheduler(server):
    return DoudizhuBotScheduler(server)


def _find_longest_run(sorted_ranks: list[int], min_len: int) -> list[int] | None:
    """从排序序列中找第一个长度 >= min_len 的连续子序列"""
    if len(sorted_ranks) < min_len:
        return None
    run = [sorted_ranks[0]]
    for i in range(1, len(sorted_ranks)):
        if sorted_ranks[i] == run[-1] + 1:
            run.append(sorted_ranks[i])
        else:
            if len(run) >= min_len:
                return run
            run = [sorted_ranks[i]]
    return run if len(run) >= min_len else None

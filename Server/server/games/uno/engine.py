"""UNO 引擎 — 2-10 人房间制

位置: lobby（大厅）/ uno#房间号（房间内）

房间外壳（建房/进出/准备/邀请/踢人/断线/Bot 调度/结算编排）来自
``core.room_engine.RoomGameEngine``；本模块只保留 UNO 玩法。
"""

from __future__ import annotations

import logging

from ...core.room_engine import RoomBotScheduler, RoomGameEngine
from ...msg_types import COMMANDS_UPDATE, GAME, LOCATION_UPDATE, ROOM_UPDATE
from .cards import COLOR_NAMES, DARK_COLORS, LIGHT_COLORS
from .room import MIN_PLAYERS, UnoRoom

logger = logging.getLogger(__name__)


class UnoEngine(RoomGameEngine):
    """UNO 引擎"""

    game_key = 'uno'
    display_name = 'UNO'
    underfilled_start = 'confirm'
    room_class = UnoRoom
    min_players = MIN_PLAYERS
    bot_action = 'bot_play'
    bot_delay_range = (1.0, 3.0)
    _HELP_TEXT = RoomGameEngine.load_data_text(__file__, 'help.txt')
    _REWARDS = RoomGameEngine.load_data_json(__file__, 'rewards.json')

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
            'play': '_cmd_play',
            'draw': '_cmd_draw',
            'uno': '_cmd_uno',
            'pass': '_cmd_pass',
            'challenge': '_cmd_challenge',
            'forfeit': '_cmd_forfeit',
        },
    }

    # ── 文案（UNO 的历史措辞在游戏名两侧留空格）──

    def _text_created(self, room_id: str) -> str:
        return f'创建了 {self.display_name} 房间 #{room_id}'

    def _text_start(self) -> str:
        return f'{self.display_name} 开始！'

    def _text_left(self) -> str:
        return f'离开了 {self.display_name}。'

    # ── 玩法指令 ──

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
        room.reset_match()
        room.state = 'waiting'

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

    def _settle_player(self, room, player, player_data) -> bool:
        from copy import deepcopy
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        has_bots = bool(room.bots)
        outcome = 'win' if player == room.winner else 'loss'
        exp, gold = self._REWARDS[outcome]
        working = deepcopy(player_data)
        self._apply_game_result(working, outcome)
        rank_change = self._update_player_rank(
            working, outcome, has_bots,
        )
        if has_bots:
            gold = int(
                exp * self._REWARDS.get('gold_ratio_bot', 0.15)
            )
        current_exp = working.get('exp', 0)
        working['exp'] = current_exp + exp
        check_level_up(working)
        current_gold = working.get('gold', 0)
        working['gold'] = max(0, current_gold + gold)

        try:
            PlayerManager.save_player_data(player, working)
        except OSError:
            logger.exception(
                "UNO 房间 %s 的玩家 %s 结算保存失败，等待重试",
                room.room_id, player)
            return False

        room._settlement_results[player] = {
            'exp': exp,
            'gold': gold,
            'rank_change': rank_change,
        }
        room._settled_players.add(player)
        working.pop('password_hash', None)
        player_data.clear()
        player_data.update(working)
        return True

    def _build_settlement_messages(self, lobby, room, caller):
        send_to_players = {}
        refresh_status = []
        caller_messages = None
        location = self._loc(room)
        rank_changes = {
            player: result['rank_change']
            for player, result in room._settlement_results.items()
        }
        for player in room.players:
            settlement = room._settlement_results.get(player)
            if settlement is None:
                continue
            refresh_status.append(player)
            lobby.set_player_location(player, location)
            board = room.get_game_data(viewer=player)
            board['rank_changes'] = rank_changes
            result_text = self._format_result(player, room, settlement)
            messages = [
                {'type': GAME, 'text': result_text},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': location},
            ]
            if player == caller:
                caller_messages = messages
            else:
                send_to_players[player] = messages
        return caller_messages, send_to_players, refresh_status

    @staticmethod
    def _finalize_settlement(lobby, room, send_to_players: dict) -> None:
        room.state = 'waiting'
        room._settlement_retry_scheduled = False
        room.hands.clear()
        room._result_pending = {
            player for player in room.players if not room.is_bot(player)
        }

        for player in send_to_players:
            player_data = lobby.online_players.get(player)
            if not player_data:
                continue
            location = lobby.get_player_location(player)
            commands = lobby.get_commands_for_location(
                location, player_data,
            )
            send_to_players[player].append({
                'type': COMMANDS_UPDATE,
                'commands': commands,
            })

    def _format_result(self, player, room, settlement) -> str:
        exp = settlement['exp']
        gold = settlement['gold']
        rc = settlement['rank_change']
        lines = []
        if room.winner:
            lines.append(f'{room.winner} 获胜！')
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

    # ── 结算钩子 ──

    def _settlement_players(self, room) -> list[str]:
        return list(room.players)

    # ── 对局中断线 ──

    def _match_disconnect(self, lobby, room, player_name):
        """有人离线，本局结束并清理房间。"""
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
        return [{
            'send_to_players': send_to_players,
            'refresh_room_list': True,
        }]


class UnoBotScheduler(RoomBotScheduler):
    """UNO Bot 调度器"""

    def __init__(self, server):
        super().__init__(
            server, 'uno', bot_action='bot_play', delay_range=(1.0, 3.0))

    def _broadcast(self, engine, room, msg):
        super()._broadcast(engine, room, msg)
        if room.state == 'finished':
            self._handle_finish(engine, room)
        else:
            for t in engine._maybe_schedule_bot(room):
                self.handle_schedule(t)


    def _bot_move(self, engine, lobby, room, bot_name):
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


def create_bot_scheduler(server):
    return UnoBotScheduler(server)

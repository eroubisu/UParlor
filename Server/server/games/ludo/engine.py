"""飞行棋引擎 — 2-4 人房间制

位置: lobby（大厅）/ ludo#房间号（房间内）

房间外壳（建房/进出/准备/邀请/踢人/断线/Bot 调度/结算编排）来自
``core.room_engine.RoomGameEngine``；本模块只保留飞行棋玩法。
"""

from __future__ import annotations

import logging

from ...core.room_engine import RoomBotScheduler, RoomGameEngine
from ...msg_types import COMMANDS_UPDATE, GAME, LOCATION_UPDATE, ROOM_UPDATE
from .board import COLOR_NAMES
from .room import MIN_PLAYERS, LudoRoom

logger = logging.getLogger(__name__)


class LudoEngine(RoomGameEngine):
    """飞行棋引擎"""

    game_key = 'ludo'
    display_name = '飞行棋'
    underfilled_start = 'forbid'
    room_class = LudoRoom
    min_players = MIN_PLAYERS
    bot_action = 'bot_turn'
    bot_delay_range = (1.0, 2.5)
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
            'roll': '_cmd_roll',
            'move': '_cmd_move',
            'forfeit': '_cmd_forfeit',
        },
    }

    # ── 玩法指令 ──

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

    def _settle_player(self, room, player, player_data) -> bool:
        from copy import deepcopy
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        # 名次与人数在调用点取自已结束的对局，保持与重试前一致。
        rank_index = room.rankings.index(player)
        player_count = len(room.players)
        has_bots = bool(room.bots)
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
            result_text = self._format_result(player, room, settlement)
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

    def _format_result(self, player, room, settlement) -> str:
        rank_idx = settlement['rank_index']
        exp = settlement['exp']
        gold = settlement['gold']
        rc = settlement['rank_change']
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

    # ── 结算钩子 ──

    def _settlement_players(self, room) -> list[str]:
        return list(room.rankings)

    def _finalize_settlement(self, lobby, room, send_to_players) -> None:
        self._finish_settlement(room)
        self._append_settlement_commands(lobby, send_to_players)

    # ── 对局中断线 ──

    def _match_disconnect(self, lobby, room, player_name):
        """有人离线，游戏强制退回等待界面。"""
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
                    {'type': ROOM_UPDATE, 'room_data': td},
                ]
                cmds = lobby.get_commands_for_location(self._loc(room), pd)
                msgs.append({'type': COMMANDS_UPDATE, 'commands': cmds})
                send_to_players[p] = msgs

        return [{
            'send_to_players': send_to_players,
            'refresh_room_list': True,
        }]


class LudoBotScheduler(RoomBotScheduler):
    """飞行棋 Bot 调度器"""

    def __init__(self, server):
        super().__init__(
            server, 'ludo', bot_action='bot_turn', delay_range=(1.0, 2.5))


    def _bot_move(self, engine, lobby, room, bot_name):
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


def create_bot_scheduler(server):
    return LudoBotScheduler(server)

"""
麻将机器人调度器
从 chat_server.py 迁移，管理 Bot 的定时出牌、吃碰杠决策、立直自动摸切
"""

import threading

from .messages import (build_discard_broadcast, build_room_broadcast,
                       build_win_broadcast, build_ryuukyoku_broadcast,
                       build_after_pass_broadcast)


class MahjongBotScheduler:
    """麻将机器人调度器

    Args:
        engine_provider: callable() → MahjongEngine（延迟获取引擎）
        server: 网络层对象，需提供:
            - dispatch_game_result(result)
            - send_to_player(player_name, data)
    """

    def __init__(self, engine_provider, server):
        self._get_engine = engine_provider
        self.server = server
        self.bot_timers = {}  # {room_id: Timer}

    def _get_room(self, room_id):
        engine = self._get_engine()
        return engine.get_room(room_id) if engine else None

    # ==================== 调度入口 ====================

    def schedule_bot_play(self, room_id, bot_name, delay=0.8):
        """安排机器人打牌"""
        if room_id in self.bot_timers:
            self.bot_timers[room_id].cancel()
        timer = threading.Timer(delay, self._bot_auto_play, args=[room_id, bot_name])
        self.bot_timers[room_id] = timer
        timer.start()

    def schedule_bot_pass(self, room_id, tile, from_player, delay=0.8):
        """安排机器人自动 pass"""
        timer = threading.Timer(delay, self._bot_auto_pass, args=[room_id, tile, from_player])
        timer.start()

    def schedule_riichi_auto_discard(self, room_id, player_name, delay=0.8):
        """安排立直玩家自动摸切"""
        timer = threading.Timer(delay, self._riichi_auto_discard, args=[room_id, player_name])
        timer.start()

    def cancel_timer(self, room_id):
        """取消房间定时器"""
        if room_id in self.bot_timers:
            self.bot_timers[room_id].cancel()
            del self.bot_timers[room_id]

    def handle_schedule(self, task):
        """通用调度入口 — 由 dispatch_game_result 调用"""
        action = task.get('action')
        if action == 'bot_play':
            self.schedule_bot_play(task['room_id'], task['player'], task.get('delay', 0.8))
        elif action == 'bot_pass':
            self.schedule_bot_pass(task['room_id'], task['tile'], task['from_player'])
        elif action == 'riichi_auto':
            self.schedule_riichi_auto_discard(task['room_id'], task['player'])
        elif action == 'cancel_timer':
            self.cancel_timer(task['room_id'])

    # ==================== 立直自动摸切 ====================

    def _riichi_auto_discard(self, room_id, player_name):
        """立直玩家自动摸切"""
        try:
            room = self._get_room(room_id)
            if not room or room.state != 'playing':
                return

            pos = room.get_position(player_name)
            if pos < 0:
                return

            if room.current_turn != pos or not room.riichi[pos]:
                return

            if room.waiting_for_action:
                return

            hand = room.hands[pos]
            if not hand:
                return

            drawn_tile = hand[-1] if hand else None
            if drawn_tile and room.can_win(hand[:-1], drawn_tile):
                return  # 能自摸就不自动摸切

            tile_to_discard = hand[-1]

            if not room.discard_tile(pos, tile_to_discard):
                return

            # 通知立直玩家自己
            tenpai_analysis = room.get_tenpai_analysis(pos)
            self.server.dispatch_game_result({
                'send_to_players': {
                    player_name: [
                        {'type': 'game', 'text': f"\U0001f512 立直中，自动摸切 [{tile_to_discard}]"},
                        {'type': 'hand_update', 'hand': room.hands[pos],
                         'drawn': None, 'tenpai_analysis': tenpai_analysis},
                    ]
                }
            })

            self._after_discard(room_id, room, player_name, tile_to_discard)
        except Exception as e:
            print(f"[立直 Error] {player_name} 自动摸切出错: {e}")
            import traceback
            traceback.print_exc()

    # ==================== Bot 出牌 ====================

    def _bot_auto_play(self, room_id, bot_name):
        """机器人自动打牌"""
        try:
            room = self._get_room(room_id)
            if not room or room.state != 'playing':
                return

            current_player = room.get_current_player_name()
            if current_player != bot_name:
                return

            pos = room.get_position(bot_name)
            if pos < 0:
                return

            hand = room.hands[pos]
            if not hand:
                return

            from .bot_ai import get_bot_discard, get_bot_self_action

            # 先检查自摸/立直
            self_actions = self._get_bot_self_actions(room, pos)
            if self_actions:
                action_result = get_bot_self_action(room, pos, self_actions)
                if action_result:
                    action_type, param = action_result
                    if action_type == 'tsumo':
                        self._bot_do_tsumo(room_id, bot_name, pos)
                        return
                    elif action_type == 'riichi':
                        self._bot_do_riichi(room_id, bot_name, pos, param)
                        return

            tile_to_discard = get_bot_discard(room, pos)
            if not tile_to_discard:
                tile_to_discard = hand[-1]

            result = room.discard_tile(pos, tile_to_discard)
            # 吃换禁止
            if isinstance(result, tuple) and result[1] == 'kuikae':
                from .game_data import normalize_tile
                forbidden = room.kuikae_forbidden[pos]
                for t in hand:
                    if normalize_tile(t) not in forbidden:
                        tile_to_discard = t
                        break
                result = room.discard_tile(pos, tile_to_discard, force=True)

            if not result or (isinstance(result, tuple) and not result[0]):
                return

            self._after_discard(room_id, room, bot_name, tile_to_discard)
        except Exception as e:
            print(f"[Bot Error] {bot_name} 自动打牌出错: {e}")
            import traceback
            traceback.print_exc()

    # ==================== 共用：出牌后处理 ====================

    def _after_discard(self, room_id, room, discard_player, tile_to_discard):
        """出牌后统一处理：检查吃碰杠 → 下家摸牌"""
        next_pos = room.current_turn
        next_player = room.players[next_pos]

        if room.waiting_for_action:
            result = build_discard_broadcast(
                room, room_id, discard_player, tile_to_discard, next_player,
                drawn_tile=None, waiting_action=True)
            self.server.dispatch_game_result(result)
        else:
            drawn = room.draw_tile(next_pos)
            if drawn is None:
                ryuukyoku_result = room.process_ryuukyoku('exhaustive')
                room.state = 'finished'
                result = build_ryuukyoku_broadcast(
                    room, ryuukyoku_result, discard_player, tile_to_discard)
                self.server.dispatch_game_result(result)
                return

            result = build_discard_broadcast(
                room, room_id, discard_player, tile_to_discard, next_player,
                drawn_tile=drawn, waiting_action=False)
            self.server.dispatch_game_result(result)

    # ==================== Bot 自身操作 ====================

    def _get_bot_self_actions(self, room, pos):
        """获取机器人可执行的自身操作"""
        actions = {}
        hand = room.hands[pos]
        if room.just_drew and hand:
            win_tile = hand[-1]
            if room.can_win(hand[:-1], win_tile):
                actions['tsumo'] = True
        riichi_tiles = room.can_declare_riichi(pos)
        if riichi_tiles:
            actions['riichi'] = riichi_tiles
        return actions

    def _bot_do_tsumo(self, room_id, bot_name, pos):
        """机器人执行自摸"""
        room = self._get_room(room_id)
        if not room:
            return

        hand = room.hands[pos]
        tsumo_tile = hand[-1]

        result = room.process_win(pos, tsumo_tile, is_tsumo=True)
        if not result.get('success'):
            return

        room.state = 'finished'
        room.waiting_for_action = False

        self.server.dispatch_game_result({
            **build_win_broadcast(room, {
                'winner': bot_name, 'win_type': 'tsumo', 'tile': tsumo_tile,
                'yakus': result['yakus'], 'han': result['han'], 'fu': result['fu'],
                'score': result['score'], 'is_yakuman': result['is_yakuman']
            }, room.get_table_data()),
            'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                          'room_id': room_id}],
        })

    def _bot_do_riichi(self, room_id, bot_name, pos, discard_tile):
        """机器人执行立直"""
        room = self._get_room(room_id)
        if not room:
            return

        success, error = room.declare_riichi(pos, discard_tile)
        if not success:
            from .bot_ai import get_bot_discard
            tile_to_discard = get_bot_discard(room, pos)
            room.discard_tile(pos, tile_to_discard)
        else:
            result = build_room_broadcast(room, f"{bot_name} 立直！", room.get_table_data())
            self.server.dispatch_game_result(result)

        self._after_discard(room_id, room, bot_name, discard_tile)

    # ==================== Bot 吃碰杠 ====================

    def _bot_auto_pass(self, room_id, tile, from_player):
        """机器人自动 pass 所有等待操作"""
        try:
            room = self._get_room(room_id)
            if not room or room.state != 'playing':
                return

            if not room.waiting_for_action:
                return

            from .bot_ai import get_bot_action

            action_players = list(room.action_players) if hasattr(room, 'action_players') else []
            last_tile = room.last_discard

            for pos in action_players:
                player_name = room.players[pos]
                if not room.is_bot(player_name):
                    continue

                available_actions = room.check_actions(pos, last_tile)
                action = get_bot_action(room, pos, last_tile, available_actions)

                acted = False
                if action == 'win':
                    acted = self._bot_do_ron(room_id, player_name, pos, last_tile)
                elif action == 'pong':
                    acted = self._bot_do_pong(room_id, player_name, pos, last_tile)
                elif action == 'kong':
                    acted = self._bot_do_kong(room_id, player_name, pos, last_tile)

                if acted:
                    return

                # 操作失败或选择 pass → 正式过牌（含振听处理）
                room.player_pass(pos)
                if room.waiting_for_action:
                    remaining = len(room.action_players)
                    next_player = room.players[room.current_turn]
                    result = build_room_broadcast(
                        room, f"[等待操作({remaining})]，轮到 {next_player}",
                        room.get_table_data(), update_last=True)
                    self.server.dispatch_game_result(result)

            # 所有人 pass → 下家摸牌
            if not room.action_players:
                room.waiting_for_action = False
                next_pos = room.current_turn
                next_player = room.players[next_pos]

                drawn = room.draw_tile(next_pos)
                if drawn is None:
                    ryuukyoku_result = room.process_ryuukyoku('exhaustive')
                    room.state = 'finished'
                    result = build_ryuukyoku_broadcast(room, ryuukyoku_result)
                    self.server.dispatch_game_result(result)
                    return

                result = build_after_pass_broadcast(
                    room, room_id, next_player, drawn, room.get_table_data())
                self.server.dispatch_game_result(result)

                if room.is_bot(next_player):
                    self.schedule_bot_play(room_id, next_player)
        except Exception as e:
            print(f"[Bot Error] 自动pass出错: {e}")
            import traceback
            traceback.print_exc()

    def _bot_do_ron(self, room_id, bot_name, pos, tile):
        """机器人执行荣和

        Returns:
            bool: 是否成功
        """
        room = self._get_room(room_id)
        if not room:
            return False

        discarder_pos = room.last_discarder
        discarder_name = room.players[discarder_pos] if discarder_pos is not None else "?"
        result = room.process_win(pos, tile, is_tsumo=False, loser_pos=discarder_pos)
        if not result.get('success'):
            return False

        room.state = 'finished'
        room.waiting_for_action = False
        room.action_players = []

        if discarder_pos is not None and room.discards[discarder_pos]:
            from .game_data import normalize_tile
            if normalize_tile(room.discards[discarder_pos][-1]) == normalize_tile(tile):
                room.discards[discarder_pos].pop()

        self.server.dispatch_game_result({
            **build_win_broadcast(room, {
                'winner': bot_name, 'win_type': 'ron', 'tile': tile,
                'loser': discarder_name, 'yakus': result['yakus'],
                'han': result['han'], 'fu': result['fu'],
                'score': result['score'], 'is_yakuman': result['is_yakuman']
            }, room.get_table_data()),
            'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                          'room_id': room_id}],
        })
        return True

    def _bot_do_pong(self, room_id, bot_name, pos, tile):
        """机器人执行碰

        Returns:
            bool: 是否成功
        """
        room = self._get_room(room_id)
        if not room or not room.do_pong(pos, tile):
            return False
        result = build_room_broadcast(room, f"{bot_name} 碰 [{tile}]", room.get_table_data())
        self.server.dispatch_game_result(result)
        self.schedule_bot_play(room_id, bot_name, delay=0.8)
        return True

    def _bot_do_kong(self, room_id, bot_name, pos, tile):
        """机器人执行明杠

        Returns:
            bool: 是否成功
        """
        room = self._get_room(room_id)
        if not room:
            return False
        success, need_draw = room.do_kong(pos, tile)
        if not success:
            return False
        message = f"{bot_name} 杠 [{tile}]"
        if need_draw:
            drawn = room.draw_tile(pos, from_dead_wall=True)
            if drawn:
                message += "，岭上摸牌"
        result = build_room_broadcast(room, message, room.get_table_data())
        self.server.dispatch_game_result(result)
        self.schedule_bot_play(room_id, bot_name, delay=0.8)
        return True

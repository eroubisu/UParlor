"""斗地主客户端处理器"""

from __future__ import annotations

from ...protocol.handler import register_handler, GameHandlerContext, format_ai_rank_changes


class DoudizhuHandler:
    """斗地主客户端处理器"""

    game_type = 'doudizhu'

    def get_input_prefix(self, location: str) -> str | None:
        """playing 状态用 /play + 牌序号"""
        if location == 'doudizhu_playing':
            return '/play '
        return None

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        if event == 'select_menu':
            ctx.show_select_menu(
                title=data.get('title', ''),
                items=data.get('items', []),
                empty_msg=data.get('empty_msg', ''),
            )
            return True
        return False

    def on_enter_game(self, ctx: GameHandlerContext) -> None:
        ctx.ensure_panel('game_board')

    def on_leave_game(self, ctx: GameHandlerContext) -> None:
        pass

    def ai_describe(self, room_data: dict) -> str:
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            players = room_data.get('players', [])
            return f'斗地主等待中，{len(players)}/3 名玩家。'

        if state == 'bidding':
            current = room_data.get('current_player', '')
            return f'斗地主叫分阶段，轮到 {current}。'

        if state == 'playing':
            dizhu = room_data.get('dizhu', '')
            current = room_data.get('current_player', '')
            hand_counts = room_data.get('hand_counts', {})
            counts = ', '.join(f'{n}:{c}张' for n, c in hand_counts.items())
            return f'斗地主进行中，地主:{dizhu}，轮到:{current}。剩余: {counts}'

        if state == 'finished':
            winner = room_data.get('winner', '')
            desc = f'斗地主结束，{winner} 获胜。'
            rk = format_ai_rank_changes(room_data)
            if rk:
                desc += f' {rk}'
            return desc

        return '斗地主大厅。'

    def ai_on_room_update(
        self, old_data: dict | None, new_data: dict
    ) -> tuple[str, bool] | None:
        if not old_data:
            return None

        old_state = old_data.get('room_state', '')
        new_state = new_data.get('room_state', '')

        if old_state == 'bidding' and new_state == 'playing':
            dizhu = new_data.get('dizhu', '')
            return (f'{dizhu} 成为地主，游戏开始！', True)

        if old_state != 'finished' and new_state == 'finished':
            winner = new_data.get('winner', '')
            spring = new_data.get('spring', False)
            msg = f'{winner} 获胜！'
            if spring:
                msg += ' (春天)'
            return (msg, True)

        return None


register_handler(DoudizhuHandler())

"""21点客户端事件处理器"""

from __future__ import annotations

from ...protocol.handler import register_handler, GameHandlerContext, format_ai_rank_changes


class BlackjackClientHandler:
    """21点客户端事件处理器"""

    game_type = 'blackjack'

    def get_input_prefix(self, location: str) -> str | None:
        # 21点通过指令按钮操作，不需要文字输入前缀
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

    def ai_on_room_update(self, old_data: dict, new_data: dict) -> tuple[str, bool] | None:
        if new_data.get('room_state') == 'finished' and not (old_data or {}).get('results'):
            results = new_data.get('results', {})
            parts = []
            for name, r in results.items():
                outcome = r.get('outcome', '?')
                val = r.get('value', 0)
                parts.append(f'{name}: {outcome}({val}点)')
            if parts:
                return (f'21点结束: {", ".join(parts)}', True)
        return None

    def ai_describe(self, room_data: dict) -> str:
        state = room_data.get('room_state', 'lobby')
        if state == 'lobby':
            return '21点大厅'
        if state == 'waiting':
            return f'21点房间#{room_data.get("room_id", "?")}，等待开始'
        players_data = room_data.get('players_data', [])
        current = room_data.get('current_player')
        results = room_data.get('results')
        if results:
            parts = [f'{n}: {r.get("outcome", "?")}({r.get("value", 0)}点)'
                     for n, r in results.items()]
            desc = f'21点结束: {", ".join(parts)}'
            rk = format_ai_rank_changes(room_data)
            if rk:
                desc += f'，{rk}'
            return desc
        parts = ['21点进行中']
        for pd in players_data:
            name = pd.get('name', '?')
            val = pd.get('value', 0)
            parts.append(f'{name}({val}点)')
        if current:
            parts.append(f'轮到{current}')
        return '，'.join(parts)


register_handler(BlackjackClientHandler())

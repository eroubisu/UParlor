"""国际象棋客户端事件处理器"""

from __future__ import annotations

from ...protocol.handler import register_handler, GameHandlerContext, format_ai_rank_changes


class ChessClientHandler:
    """国际象棋客户端事件处理器"""

    game_type = 'chess'

    def get_input_prefix(self, location: str) -> str | None:
        """playing 状态直接输入 UCI 走法"""
        if location == 'chess_playing':
            return '/move '
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
        """检测国际象棋状态变化，通知 AI 旅伴"""
        if new_data.get('room_state') != 'playing':
            return None
        old_count = old_data.get('move_count', 0) if old_data else 0
        new_count = new_data.get('move_count', 0)
        if new_count <= old_count:
            return None
        history = new_data.get('history', [])
        last = history[-1] if history else '?'
        turn = new_data.get('turn', '?')
        in_check = new_data.get('in_check', False)
        check_str = '，将军！' if in_check else ''
        desc = f'国际象棋: 最近走法 {last}，轮到{"白" if turn == "white" else "黑"}方{check_str}'
        return (desc, True)

    def ai_describe(self, room_data: dict) -> str:
        state = room_data.get('room_state', 'lobby')
        if state == 'lobby':
            return '国际象棋大厅'
        if state == 'waiting':
            room_id = room_data.get('room_id', '?')
            return f'国际象棋房间#{room_id}，等待开始'
        players = room_data.get('players', [None, None])
        turn = room_data.get('turn', 'white')
        move_count = room_data.get('move_count', 0)
        result = room_data.get('result')
        if result:
            desc = f'国际象棋已结束: {result} ({room_data.get("result_reason", "")})'
            rk = format_ai_rank_changes(room_data)
            if rk:
                desc += f'，{rk}'
            return desc
        parts = [
            f'国际象棋进行中，白{players[0]} vs 黑{players[1]}',
            f'第{move_count}步，轮到{"白" if turn == "white" else "黑"}方',
        ]
        if room_data.get('in_check'):
            parts.append('将军')
        return '，'.join(parts)


register_handler(ChessClientHandler())

"""Wordle 客户端事件处理器"""

from __future__ import annotations

from ..protocol.handler import register_handler, GameHandlerContext


class WordleClientHandler:
    """Wordle 客户端事件处理器"""

    game_type = 'wordle'

    def get_input_prefix(self, location: str) -> str | None:
        """playing 状态直接输入单词即作为 guess"""
        if location == 'wordle_playing':
            return '/guess '
        # wordle_finished / wordle_room / wordle_lobby — 禁止文字输入
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


register_handler(WordleClientHandler())

"""GameBoardPanel — 通用游戏画面面板（委托 GameRenderer 渲染）"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ...state import ModuleStateManager


class GameBoardPanel(Widget):
    """通用游戏面板：接收 room_data，查找对应 GameRenderer 渲染"""

    def compose(self) -> ComposeResult:
        yield RichLog(id="game-board-log", wrap=True, highlight=True, markup=True, max_lines=500)

    def on_mount(self) -> None:
        log: RichLog = self.query_one("#game-board-log", RichLog)
        log.write("[dim]进入游戏后将在此显示游戏画面[/dim]")

    def update_room(self, room_data: dict):
        from ...game_renderer import get_renderer
        log: RichLog = self.query_one("#game-board-log", RichLog)
        game_type = room_data.get('game_type', '')
        renderer = get_renderer(game_type)
        log.clear()
        if renderer:
            state = room_data.get('state', 'waiting')
            if state == 'waiting' and hasattr(renderer, 'render_board_waiting'):
                renderer.render_board_waiting(log, room_data)
            else:
                renderer.render_board(log, room_data)
        else:
            log.write(f"[游戏面板] {game_type or '未知游戏'}")

    def clear(self):
        log: RichLog = self.query_one("#game-board-log", RichLog)
        log.clear()

    def restore(self, state: ModuleStateManager):
        if state.game_board.room_data:
            self.update_room(state.game_board.room_data)

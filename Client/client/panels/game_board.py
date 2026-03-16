"""GameBoardPanel — 通用游戏画面面板（委托 GameRenderer 渲染）"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ..config import MAX_LINES_GAME_BOARD, M_DIM, M_END
from ..state import ModuleStateManager


class GameBoardPanel(Widget):
    """通用游戏面板：接收 room_data，查找对应 GameRenderer 渲染"""

    def compose(self) -> ComposeResult:
        yield RichLog(id="game-board-log", wrap=True, highlight=True, markup=True, max_lines=MAX_LINES_GAME_BOARD)

    def on_mount(self) -> None:
        log: RichLog = self.query_one("#game-board-log", RichLog)
        log.write(f"{M_DIM}暂无游戏画面{M_END}")

    def _render_room(self, room_data: dict):
        from ..protocol.renderer import get_renderer
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

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event == 'update_room':
            (room_data,) = args
            self._render_room(room_data)
        elif event == 'clear':
            log: RichLog = self.query_one("#game-board-log", RichLog)
            log.clear()

    def restore(self, state: ModuleStateManager):
        state.game_board.set_listener(self._on_state_event)
        if state.game_board.room_data:
            self._render_room(state.game_board.room_data)

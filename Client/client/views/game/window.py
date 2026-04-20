"""游戏主窗口 — LogPanel + 游戏棋盘 + RoomControlsPanel"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal

from ...widgets.window import Window
from ..lobby.log import LogPanel
from .board import GameBoardPanel
from .controls import RoomControlsPanel


class GameWindow(Window):
    """游戏进行中主窗口"""

    DEFAULT_CSS = """
    GameWindow {
        width: 1fr;
        height: 1fr;
    }
    GameWindow > #game-log {
        dock: top;
        height: 3;
        width: 1fr;
        scrollbar-size: 0 0;
    }
    GameWindow > #game-body {
        height: 1fr;
        width: 1fr;
    }
    GameWindow > #game-body > #game-board {
        width: 1fr;
    }
    GameWindow > #game-body > #room-controls {
        width: 24;
    }
    """

    focus_grid = [["game-log"], ["game-board", "room-controls"]]
    primary_panel = 'game-board'

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos = (1, 0)  # 默认聚焦棋盘
        self._bound = False

    def compose(self) -> ComposeResult:
        yield LogPanel(id="game-log")
        with Horizontal(id="game-body"):
            yield GameBoardPanel(id="game-board")
            yield RoomControlsPanel(id="room-controls")

    def bind_state(self, st, send_fn=None) -> None:
        if self._bound:
            return
        self._bound = True
        self.query_one("#game-log", LogPanel).bind_state(st)
        board = self.query_one("#game-board", GameBoardPanel)
        board.bind_state(st, send_command=send_fn,
                         set_timer=self.app.set_timer if hasattr(self.app, 'set_timer') else None)
        rc = self.query_one("#room-controls", RoomControlsPanel)
        if send_fn:
            rc.bind_send(send_fn)

    def show(self) -> None:
        super().show()

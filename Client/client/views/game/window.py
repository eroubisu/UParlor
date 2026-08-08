"""游戏主窗口 — LogPanel + 游戏棋盘 + 右上聊天 + 右下操作"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

from ...widgets.window import Window
from ...window_engine import WindowSpec, register_window
from ...window_specs import bind_state_with_send
from ..lobby.log import LogPanel
from ..chat.content import ChatContentPanel
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
    GameWindow > #game-body > #game-right {
        width: 36;
        height: 1fr;
    }
    GameWindow > #game-body > #game-right > #game-chat {
        height: 3fr;
        width: 1fr;
        min-height: 8;
    }
    GameWindow > #game-body > #game-right > #room-controls {
        height: 1fr;
        width: 1fr;
        min-height: 6;
    }
    """

    # 同 waiting_window 的多行布局：左栏跨行，右栏分上下两行
    focus_grid = [
        ["game-log"],
        ["game-board", "game-chat"],
        ["game-board", "room-controls"],
    ]
    primary_panel = 'game-board'

    # WindowEngine 主窗口 (游戏中)
    spec = WindowSpec(
        id="game-window", title="游戏中",
        group="primary", mode="primary", order=40,
        bind=bind_state_with_send,
    )

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos = (1, 0)  # 默认聚焦棋盘
        self._bound = False

    def compose(self) -> ComposeResult:
        yield LogPanel(id="game-log")
        with Horizontal(id="game-body"):
            yield GameBoardPanel(id="game-board")
            with Vertical(id="game-right"):
                yield ChatContentPanel(id="game-chat")
                yield RoomControlsPanel(id="room-controls")

    def bind_state(self, st, send_fn=None) -> None:
        if self._bound:
            return
        self._bound = True
        self.query_one("#game-log", LogPanel).bind_state(st)
        board = self.query_one("#game-board", GameBoardPanel)
        board.bind_state(
            st, send_command=send_fn,
            set_timer=self.app.set_timer if hasattr(self.app, 'set_timer') else None,
        )
        cp = self.query_one("#game-chat", ChatContentPanel)
        cp.bind_state(st)
        cp.show_conversation("room")
        rc = self.query_one("#room-controls", RoomControlsPanel)
        if send_fn:
            rc.bind_send(send_fn)


register_window(GameWindow)

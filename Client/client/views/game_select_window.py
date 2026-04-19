"""游戏选择浮动窗口 — 左侧游戏列表 + 右侧游戏详情"""

from __future__ import annotations

from textual.app import ComposeResult

from ..widgets.window import Window
from .game_list import GameListPanel, GameSelected, FocusRight
from .game_detail import GameDetailPanel


class GameSelectWindow(Window):
    """浮动游戏选择窗口"""

    DEFAULT_CSS = """
    GameSelectWindow {
        layer: floating;
        width: 60%;
        height: 55%;
    }
    GameSelectWindow > #game-list {
        width: 20;
        height: 1fr;
    }
    GameSelectWindow > #game-detail {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["game-list", "game-detail"]]

    def __init__(self, **kw):
        super().__init__(**kw)
        self._bound = False

    def compose(self) -> ComposeResult:
        yield GameListPanel(id="game-list")
        yield GameDetailPanel(id="game-detail")

    def bind_state(self, st, send_fn) -> None:
        if self._bound:
            return
        self._bound = True
        self.query_one("#game-list", GameListPanel).bind_state(st)
        self.query_one("#game-detail", GameDetailPanel).bind_send(send_fn)

    def show(self) -> None:
        super().show()
        self.reset_focus()

    def on_game_selected(self, event: GameSelected) -> None:
        """左侧选中游戏 → 右侧显示详情"""
        event.stop()
        self.query_one("#game-detail", GameDetailPanel).show_game(event.game)

    def on_focus_right(self, event: FocusRight) -> None:
        """左侧 Enter → 聚焦右侧详情面板"""
        event.stop()
        self.focus_move('l')

"""档案浮动窗口 — 状态面板"""

from __future__ import annotations

from textual.app import ComposeResult

from ...widgets.window import Window
from .status_panel import StatusPanel


class ProfileWindow(Window):
    """浮动档案窗口"""

    DEFAULT_CSS = """
    ProfileWindow {
        layer: floating;
        width: 38%;
        height: 55%;
    }
    ProfileWindow > #status-panel {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["status-panel"]]

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos = (0, 0)
        self._bound = False

    def compose(self) -> ComposeResult:
        yield StatusPanel(id="status-panel")

    def bind_state(self, st) -> None:
        if self._bound:
            return
        self._bound = True
        self.query_one("#status-panel", StatusPanel).bind_state(st)

    def show_player_card(self, data: dict, is_self: bool = False,
                         friends: list[str] | None = None) -> None:
        """显示指定玩家的名片"""
        self.query_one("#status-panel", StatusPanel).render_card(
            data, is_self=is_self, friends=friends)

    def show(self) -> None:
        super().show()

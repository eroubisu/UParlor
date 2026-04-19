"""通知浮动窗口 — 单面板三标签"""

from __future__ import annotations

from textual.app import ComposeResult

from ..widgets.window import Window
from .notification_panel import NotificationPanel


class NotificationWindow(Window):
    """浮动通知窗口"""

    DEFAULT_CSS = """
    NotificationWindow {
        layer: floating;
        width: 50%;
        height: 55%;
    }
    NotificationWindow > #notification-panel {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["notification-panel"]]

    def __init__(self, **kw):
        super().__init__(**kw)
        self._bound = False

    def compose(self) -> ComposeResult:
        yield NotificationPanel(id="notification-panel")

    def bind_state(self, st) -> None:
        if self._bound:
            return
        self._bound = True
        self.query_one("#notification-panel", NotificationPanel).bind_state(st)

    def show(self) -> None:
        super().show()

"""设置菜单 — 教程 / 文档 / 用户档案"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message

from ..widgets.panel import Panel
from ..widgets.window import Window

# ── 设置选项 ──

_OPTIONS = [
    ('tutorial', '打开教程'),
    ('docs', '打开文档'),
    ('profile', '打开用户档案'),
]


class SettingsPanel(Panel):
    """设置选项列表"""

    icon_align = True
    hide_scrollbar = True

    class Selected(Message):
        """选中某个设置项"""
        def __init__(self, target: str) -> None:
            super().__init__()
            self.target = target

    _labels = [name for _, name in _OPTIONS]

    def on_mount(self) -> None:
        super().on_mount()
        self._redraw()

    def nav(self, action: str) -> None:
        if not self._cursor_nav(
            action, len(_OPTIONS),
            on_enter=lambda: self.post_message(self.Selected(_OPTIONS[self._cursor][0])),
            redraw=self._redraw,
        ):
            super().nav(action)

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._redraw()

    def _redraw(self) -> None:
        self.update(self._render_cursor_items(self._labels))


class SettingsWindow(Window):
    """设置浮窗"""

    DEFAULT_CSS = """
    SettingsWindow {
        layer: floating;
        width: 30;
        height: 9;
    }
    SettingsWindow > #settings-panel {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["settings-panel"]]

    def compose(self) -> ComposeResult:
        yield SettingsPanel(id="settings-panel")

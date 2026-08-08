"""Settings menu and local input policy."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message

from ...widgets.panel import Panel
from ...widgets.window import Window
from ...window_engine import Option, WindowSpec, register_window

# ── 设置选项 ──

_OPTIONS = [
    ('tutorial', '打开教程'),
    ('docs', '打开文档'),
    ('ctrl_c', '屏蔽 Ctrl+C'),
    ('quit', '退出 UParlor'),
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

    class QuitRequested(Message):
        """The player confirmed application exit."""

    def on_mount(self) -> None:
        super().on_mount()
        self._confirming_quit = False
        self._redraw()

    def nav(self, action: str) -> None:
        if self._confirming_quit:
            def _quit() -> None:
                self.post_message(self.QuitRequested())

            def _dismiss() -> None:
                self._confirming_quit = False
                self._redraw()

            self._nav_confirm(action, _quit, _dismiss)
            if self._confirming_quit:
                self.update(self._render_confirm("确认退出 UParlor?"))
            return
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self._redraw()
        elif selected is not None:
            if selected.id == "ctrl_c":
                from ...storage import get_block_ctrl_c, set_block_ctrl_c

                set_block_ctrl_c(not get_block_ctrl_c())
                self._redraw()
            elif selected.id == "quit":
                self._confirming_quit = True
                self.update(self._render_confirm("确认退出 UParlor?"))
            else:
                self.post_message(self.Selected(selected.id))
        else:
            super().nav(action)

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._redraw()

    def reflow_content(self) -> None:
        self._redraw()

    def _redraw(self) -> None:
        from ...storage import get_block_ctrl_c

        labels = {
            option_id: label
            for option_id, label in _OPTIONS
        }
        labels["ctrl_c"] = (
            f"屏蔽 Ctrl+C：{'开' if get_block_ctrl_c() else '关'}"
        )
        self.set_options(
            (
                Option(option_id, labels[option_id])
                for option_id, _ in _OPTIONS
            ),
            "settings",
        )
        self.update(self.render_options())


class SettingsWindow(Window):
    """设置浮窗"""

    DEFAULT_CSS = """
    SettingsWindow {
        layer: floating;
        width: 30;
        height: 12;
    }
    SettingsWindow > #settings-panel {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["settings-panel"]]

    spec = WindowSpec(
        id="settings-window", title="设置", menu=True,
        group="root", order=60,
    )

    def compose(self) -> ComposeResult:
        yield SettingsPanel(id="settings-panel")


register_window(SettingsWindow)

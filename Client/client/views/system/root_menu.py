"""Centered selectable root menu opened by Space."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message

from ...widgets.panel import Panel
from ...widgets.window import Window
from ...window_engine import Option, WindowSpec, register_window


class RootMenuPanel(Panel):
    """List every registered root action without exposing shortcut keys."""

    title = "菜单"
    icon_align = True
    hide_scrollbar = True

    class Selected(Message):
        def __init__(self, window_id: str) -> None:
            super().__init__()
            self.window_id = window_id

    def on_mount(self) -> None:
        super().on_mount()
        self.refresh_items()

    def refresh_items(self) -> None:
        from ...window_engine.registry import get_registry

        self.set_options(
            (
                Option(spec.id, spec.title)
                for spec in get_registry().menu_entries("root")
            ),
            "root-menu",
        )
        self.update(self.render_options())

    def nav(self, action: str) -> None:
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self.update(self.render_options())
        elif selected is not None:
            self.post_message(self.Selected(selected.id))

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self.refresh_items()

    def reflow_content(self) -> None:
        self.refresh_items()


class RootMenuWindow(Window):
    """Small centered popup containing the application's root actions."""

    DEFAULT_CSS = """
    RootMenuWindow {
        layer: floating;
        width: 30;
        height: 18;
    }
    RootMenuWindow > #root-menu-panel {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["root-menu-panel"]]

    spec = WindowSpec(
        id="root-menu-window",
        title="菜单",
        group="system",
        order=10,
        mode="popup",
    )

    def compose(self) -> ComposeResult:
        yield RootMenuPanel(id="root-menu-panel")


register_window(RootMenuWindow)

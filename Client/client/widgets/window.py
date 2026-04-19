"""Window — Panel 布局容器 / 浮动窗口"""

from __future__ import annotations
from textual.widget import Widget
from textual.app import ComposeResult
from .panel import Panel


class Window(Widget):

    DEFAULT_CSS = """
    Window {
        layer: windows;
        display: none;
        width: 90%; height: 85%;
        background: transparent;
        layout: horizontal;
    }
    Window.visible {
        display: block;
    }
    """

    focus_grid: list[list[str]] = []
    primary_panel: str | None = None

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos: tuple[int, int] = (0, 0)
        self._panels: dict[str, Panel] = {}

    def on_mount(self) -> None:
        for p in self.query(Panel):
            if p.id:
                self._panels[p.id] = p
        r, c = self._focus_pos
        if self.focus_grid and r < len(self.focus_grid) and c < len(self.focus_grid[r]):
            pid = self.focus_grid[r][c]
            if pid in self._panels:
                self._panels[pid].add_class("-focused")

    @property
    def focused_panel(self) -> Panel | None:
        if not self.focus_grid:
            return None
        r, c = self._focus_pos
        return self._panels.get(self.focus_grid[r][c])

    def focus_move(self, direction: str) -> None:
        if not self.focus_grid:
            return
        r, c = self._focus_pos
        rows = len(self.focus_grid)
        match direction:
            case "k":  r = max(0, r - 1)
            case "j":  r = min(rows - 1, r + 1)
            case "h":  c = max(0, c - 1)
            case "l":  c = min(len(self.focus_grid[r]) - 1, c + 1)
            case _:    return
        c = min(c, len(self.focus_grid[r]) - 1)
        if (r, c) == self._focus_pos:
            return
        old = self.focused_panel
        self._focus_pos = (r, c)
        new = self.focused_panel
        if old:
            old.remove_class("-focused")
            if hasattr(old, 'on_panel_blur'):
                old.on_panel_blur()
        if new:
            new.add_class("-focused")
            if hasattr(new, 'on_panel_focus'):
                new.on_panel_focus()

    def reset_focus(self) -> None:
        """重置焦点到初始位置 (0, 0)"""
        if self._focus_pos == (0, 0):
            return
        old = self.focused_panel
        self._focus_pos = (0, 0)
        new = self.focused_panel
        if old:
            old.remove_class("-focused")
            if hasattr(old, 'on_panel_blur'):
                old.on_panel_blur()
        if new:
            new.add_class("-focused")
            if hasattr(new, 'on_panel_focus'):
                new.on_panel_focus()

    def nav(self, action: str) -> None:
        if p := self.focused_panel:
            p.nav(action)

    def show(self) -> None:
        for p in self._panels.values():
            p.reset_cursor()
        self._focus_to_primary()
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    def _focus_to_primary(self) -> None:
        """将焦点移到 primary_panel（如果已设置）"""
        pid = self.primary_panel
        if not pid or not self.focus_grid:
            return
        for r, row in enumerate(self.focus_grid):
            for c, cell in enumerate(row):
                if cell == pid:
                    if (r, c) != self._focus_pos:
                        old = self.focused_panel
                        self._focus_pos = (r, c)
                        new = self.focused_panel
                        if old:
                            old.remove_class("-focused")
                        if new:
                            new.add_class("-focused")
                    return

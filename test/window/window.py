"""Window — Panel 布局容器"""

from __future__ import annotations
from textual.widget import Widget
from panel import Panel


class Window(Widget):

    DEFAULT_CSS = """
    Window {
        width: 1fr; height: 1fr; layout: horizontal;
        background: transparent;
    }
    Window > Panel.-focused {
        border: round #5a5a5a;
    }
    """

    focus_grid: list[list[str]] = []

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos: tuple[int, int] = (0, 0)
        self._panels: dict[str, Panel] = {}

    def on_mount(self) -> None:
        for p in self.query(Panel):
            if p.id:
                self._panels[p.id] = p
        if self.focus_grid and self.focus_grid[0]:
            pid = self.focus_grid[0][0]
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
        if (r, c) == self._focus_pos:
            return
        old = self.focused_panel
        self._focus_pos = (r, c)
        new = self.focused_panel
        if old:
            old.remove_class("-focused")
        if new:
            new.add_class("-focused")

    def nav(self, action: str) -> None:
        if p := self.focused_panel:
            p.nav(action)

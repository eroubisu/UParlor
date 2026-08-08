"""Window — Panel 布局容器 / 浮动窗口"""

from __future__ import annotations
from typing import Callable

from textual.widget import Widget
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
    Window.-primary {
        position: absolute;
        width: 100%;
        height: 100%;
    }
    Window.-layout-pending {
        position: absolute;
        offset: -100vw -100vh;
    }
    Window.-popup {
        layer: overlay;
    }
    """

    focus_grid: list[list[str]] = []
    primary_panel: str | None = None
    presentation_timeout: float | None = None

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos: tuple[int, int] = (0, 0)
        self._default_focus_pos: tuple[int, int] = (0, 0)
        self._panels: dict[str, Panel] = {}
        self._show_revision = 0
        self._activation_managed = False
        self._active = True
        self._presentation_timeout_revision = -1
        self._presentation_observer: Callable[[str], None] | None = None
        self._staged_presentation: Callable[[], None] | None = None

    def set_presentation_observer(self, observer: Callable[[str], None]) -> None:
        self._presentation_observer = observer

    def stage_presentation(self, prepare: Callable[[], None]) -> None:
        """Stage target-only content for the next measured presentation."""
        self._staged_presentation = prepare

    def cancel_staged_presentation(self) -> None:
        """Discard target-only content when presentation cannot proceed."""
        self._staged_presentation = None

    def on_mount(self) -> None:
        self._default_focus_pos = self._focus_pos
        for p in self.query(Panel):
            if p.id:
                self._panels[p.id] = p
        r, c = self._focus_pos
        if self.focus_grid and r < len(self.focus_grid) and c < len(self.focus_grid[r]):
            pid = self.focus_grid[r][c]
            if pid in self._panels:
                self._panels[pid].add_class("-focused")
        self.sync_primitives()

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
        self._focus_pos = (r, c)
        self._apply_focus_change()

    def focus_panel(self, panel_id: str) -> bool:
        """Focus a panel by id without exposing the focus-grid internals."""
        for row, cells in enumerate(self.focus_grid):
            for column, cell in enumerate(cells):
                if cell == panel_id and cell in self._panels:
                    if (row, column) != self._focus_pos:
                        self._focus_pos = (row, column)
                        self._apply_focus_change()
                    return True
        return False

    def _apply_focus_change(self) -> None:
        """Synchronize panel focus classes and primitive lifecycle."""
        new = self.focused_panel
        for panel in self._panels.values():
            if panel is new:
                continue
            panel.remove_class("-focused")
            if hasattr(panel, "on_panel_blur"):
                panel.on_panel_blur()
        if new:
            new.add_class("-focused")
            if hasattr(new, 'on_panel_focus'):
                new.on_panel_focus()
        self.sync_primitives()

    def reset_focus(self) -> None:
        """Restore the focus position declared by this window."""
        if self._focus_pos == self._default_focus_pos:
            return
        self._focus_pos = self._default_focus_pos
        self._apply_focus_change()

    def nav(self, action: str) -> None:
        if p := self.focused_panel:
            p.nav(action)

    def show(self) -> None:
        self._show_revision += 1
        revision = self._show_revision
        self._presentation_timeout_revision = -1
        self.prepare_presentation()
        self.add_class("-layout-pending")
        self.add_class("visible")
        self.reset_focus()
        self._focus_to_primary()
        self.call_after_refresh(self._prepare_after_show, revision)

    def prepare_presentation(self) -> None:
        """Reset window-owned readiness before the shared measurement cycle."""

    def _prepare_after_show(self, revision: int) -> None:
        """Prepare measured content while the newly opened window stays hidden."""
        if revision != self._show_revision or not self.has_class("visible"):
            return
        staged = self._staged_presentation
        self._staged_presentation = None
        if staged is not None:
            staged()
        for p in self._panels.values():
            p.reset_cursor()
        self._focus_to_primary()
        self.sync_primitives()
        self._report_presentation("measured")
        self.call_after_refresh(self._reveal_after_show, revision)

    def _reveal_after_show(self, revision: int) -> None:
        """Reflow once more after scrollbar layout, then reveal the window."""
        if revision != self._show_revision or not self.has_class("visible"):
            return
        self._reflow_content()
        self._focus_to_primary()
        self.sync_primitives()
        if not self.presentation_ready():
            self._schedule_presentation_timeout(revision)
            return
        # Put the complete target frame on-screen before the engine hides the
        # previous primary. Both class mutations still commit in this turn.
        self.remove_class("-layout-pending")
        self._report_presentation("presenting")
        self._report_presentation("presented")

    def presentation_ready(self) -> bool:
        """Return whether measured content is ready to become visible."""
        return True

    def on_presentation_timeout(self) -> None:
        """Prepare a stable fallback when asynchronous first-frame data fails."""

    def _schedule_presentation_timeout(self, revision: int) -> None:
        timeout = self.presentation_timeout
        if timeout is None or self._presentation_timeout_revision == revision:
            return
        self._presentation_timeout_revision = revision
        self.set_timer(
            timeout,
            lambda: self._on_presentation_timeout(revision),
        )

    def _on_presentation_timeout(self, revision: int) -> None:
        if (
            revision != self._show_revision
            or not self.has_class("visible")
            or not self.has_class("-layout-pending")
        ):
            return
        self.on_presentation_timeout()
        self.resume_presentation()

    def resume_presentation(self) -> None:
        """Retry the final presentation stage after asynchronous data arrives."""
        if self.has_class("visible") and self.has_class("-layout-pending"):
            self.call_after_refresh(
                self._reveal_after_show, self._show_revision,
            )

    def hide(self) -> None:
        self._show_revision += 1
        self.cancel_staged_presentation()
        for panel in self._panels.values():
            if hasattr(panel, "leave_insert"):
                panel.leave_insert(preserve=True)
        self.remove_class("visible")
        self.remove_class("-layout-pending")
        if self.is_mounted:
            self.screen.refresh(layout=True)

    def set_active(self, active: bool) -> None:
        """Expose whether this is the single window receiving navigation."""
        self._activation_managed = True
        self._active = active
        self.set_class(active, "-active")

    def sync_primitives(self) -> None:
        """Run after open/close/activate/deactivate/resize lifecycle changes."""
        window_active = not self._activation_managed or self._active
        active_panel = self.focused_panel if window_active else None
        for panel in self._panels.values():
            if hasattr(panel, "sync_primitives"):
                panel.sync_primitives(active=panel is active_panel)

    def on_resize(self, _event) -> None:
        del _event
        self.sync_primitives()

    def _reflow_content(self) -> None:
        if not self.has_class("visible"):
            return
        for panel in self._panels.values():
            panel.reflow_content()

    def _focus_to_primary(self) -> None:
        """将焦点移到 primary_panel（如果已设置）"""
        pid = self.primary_panel
        if not pid or not self.focus_grid:
            return
        self.focus_panel(pid)

    def _report_presentation(self, stage: str) -> None:
        if self._presentation_observer is not None:
            self._presentation_observer(stage)

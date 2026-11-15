"""Shared game status panel rendered from the active game renderer."""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ...config import COLOR_BORDER, GAME_STATUS_MAX_PAGES
from ...protocol.renderer import GameStatusContent, get_renderer
from ...widgets.panel import Panel
from ...window_engine import Divider

_log = logging.getLogger(__name__)


class GameStatusPanel(Panel):
    """Display each game's declared status surface in the right rail."""

    title = "状态"
    full_width_content = True
    # 面板挂载时还不知道游戏要用几页，先按上限建好标签页，再按页数显示
    MAX_PAGES = GAME_STATUS_MAX_PAGES

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = None

    def compose_content(self) -> ComposeResult:
        yield Static("", id="game-status-header")
        yield Divider(style=COLOR_BORDER, id="game-status-divider")
        for index in range(self.MAX_PAGES):
            with VerticalScroll(classes="tab", id=f"t{index}"):
                yield Static("", classes="content full-width")

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#game-status-header", Static).display = False
        self.query_one("#game-status-divider", Divider).display = False
        for index in range(1, self.MAX_PAGES):
            self.query_one(f"#t{index}", VerticalScroll).display = False

    def bind_state(self, state) -> None:
        if self._state is not None:
            self._state.game_board.remove_listener(self._on_event)
            self._state.game_interaction.remove_listener(self._on_event)
        self._state = state
        state.game_board.add_listener(self._on_event)
        state.game_interaction.add_listener(self._on_event)
        self._refresh()

    def _on_event(self, _event: str, *_args) -> None:
        self._refresh()

    def reflow_content(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        room_data = self._state.game_board.room_data if self._state else {}
        game_type = room_data.get("game_type", "")
        renderer = get_renderer(game_type) if game_type else None
        if renderer is None:
            self.update("")
            return
        self.styles.height = renderer.status_height(room_data)
        interaction = None
        if room_data.get("room_state") == "playing":
            interaction = self._state.game_interaction.snapshot(game_type)
        status = renderer.render_status(room_data, interaction)
        header = self.query_one("#game-status-header", Static)
        divider = self.query_one("#game-status-divider", Divider)
        has_header = status.header is not None
        header.display = has_header
        divider.display = has_header
        header.update(status.header or "")
        self._apply_pages(status)
        self.border_title = self._render_tabs() or "状态"

    def _apply_pages(self, status: GameStatusContent) -> None:
        """把渲染器给的页面装进标签页；只有一页时不显示标签栏。"""
        if status.pages:
            pages = list(status.pages)
        elif status.body is not None:
            pages = [("", status.body)]
        else:
            pages = [("", "")]
        if len(pages) > self.MAX_PAGES:
            _log.warning('状态面板最多 %d 页，%s 声明了 %d 页，多出的不会显示',
                         self.MAX_PAGES, type(status).__name__, len(pages))
            pages = pages[:self.MAX_PAGES]
        named = all(name for name, _ in pages)
        self.tabs = [name for name, _ in pages] if len(pages) > 1 and named \
            else []
        self._active = min(self._active, len(pages) - 1)
        for index in range(self.MAX_PAGES):
            visible = index < len(pages) and index == self._active
            self.query_one(f"#t{index}", VerticalScroll).display = visible
            body = pages[index][1] if index < len(pages) else ""
            self.update(body or "", tab=index)

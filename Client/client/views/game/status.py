"""Shared game status panel rendered from the active game renderer."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ...config import COLOR_BORDER
from ...protocol.renderer import get_renderer
from ...widgets.panel import Panel
from ...window_engine import Divider


class GameStatusPanel(Panel):
    """Display each game's declared status surface in the right rail."""

    title = "状态"
    full_width_content = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = None

    def compose_content(self) -> ComposeResult:
        yield Static("", id="game-status-header")
        yield Divider(style=COLOR_BORDER, id="game-status-divider")
        with VerticalScroll(classes="tab", id="t0"):
            yield Static("", classes="content full-width")

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#game-status-header", Static).display = False
        self.query_one("#game-status-divider", Divider).display = False

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
        self.update(status.body or "")
        self.border_title = "状态"
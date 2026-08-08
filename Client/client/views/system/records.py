"""Full record window backed by the command record state."""

from __future__ import annotations

from textual.app import ComposeResult

from ...widgets.panel import Panel
from ...widgets.window import Window
from ...window_engine import WindowSpec, register_window
from ...window_specs import bind_state, logged_in


_INITIAL_RECORD_LIMIT = 16


class RecordsPanel(Panel):
    """Readable projection of the most recent record entries."""

    title = "记录"

    def bind_state(self, state) -> None:
        self.update("\n".join(state.cmd.lines[-_INITIAL_RECORD_LIMIT:]))


class RecordsWindow(Window):
    """Tall floating window for reading recent records."""

    DEFAULT_CSS = """
    RecordsWindow {
        layer: floating;
        width: 68%;
        height: 72%;
    }
    RecordsWindow > #records-panel {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["records-panel"]]

    spec = WindowSpec(
        id="records-window",
        title="记录",
        menu=True,
        group="root",
        order=15,
        preconditions=(logged_in,),
        bind=bind_state,
    )

    def compose(self) -> ComposeResult:
        yield RecordsPanel(id="records-panel")

    def bind_state(self, state) -> None:
        self.query_one("#records-panel", RecordsPanel).bind_state(state)


register_window(RecordsWindow)
"""Full record window backed by the command record state."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll

from ...widgets.panel import Panel
from ...widgets.window import Window
from ...window_engine import WindowSpec, register_window
from ...window_specs import bind_state, logged_in


_INITIAL_RECORD_LIMIT = 16


class RecordsPanel(Panel):
    """Readable projection of the most recent record entries."""

    title = "记录"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._state = None

    def bind_state(self, state) -> None:
        # 窗口每次打开都会重新绑定：监听只订一次，别让同一条记录被追加几遍
        if self._state is not state:
            if self._state is not None:
                self._state.cmd.remove_listener(self._on_state)
            self._state = state
            state.cmd.add_listener(self._on_state)
        self.update("\n".join(state.cmd.lines[-_INITIAL_RECORD_LIMIT:]))
        self.call_after_refresh(
            self.query_one("#t0", VerticalScroll).scroll_end, animate=False)

    def _on_state(self, event: str, *args) -> None:
        """窗口开着的时候新记录接着往下写，不让它停在打开那一刻的样子。"""
        match event:
            case "add_line":
                text, kw = args
                if kw.get("update_last"):
                    self.replace_last(text)
                else:
                    self.append(text)
            case "clear":
                self.update("")


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
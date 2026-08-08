"""Modal shown when another client replaces the current account session."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from ..config import COLOR_FG_SECONDARY, M_BOLD, M_END
from ..input_actions import navigation_action
from ..window_engine import Option, SelectList


class SessionOfflineDialog(ModalScreen[str]):
    """Require an explicit choice after the server ends this session."""

    DEFAULT_CSS = f"""
    SessionOfflineDialog {{
        align: center middle;
        background: transparent;
    }}

    #session-offline-dialog {{
        width: 52;
        height: auto;
        border: round {COLOR_FG_SECONDARY};
        padding: 1 2;
        background: transparent;
    }}
    """

    _OPTIONS = (
        ("login", "返回登录界面"),
        ("exit", "退出客户端"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.selection = SelectList(
            (Option(option_id, label) for option_id, label in self._OPTIONS),
            "session-offline",
        )

    def compose(self) -> ComposeResult:
        yield Static(self._render_content(), id="session-offline-dialog")

    def _render_content(self) -> str:
        lines = [
            f"{M_BOLD}账号已下线{M_END}",
            "",
            "当前账号已在其他客户端登录，本会话已结束。",
            "",
        ]
        lines.append(
            self.selection.render(
                46,
                selected_style=M_BOLD.strip("[]"),
                idle_style="dim",
            )
        )
        return "\n".join(lines)

    def nav(self, action: str) -> None:
        selected = self.selection.handle(action)
        if action not in ("up", "down", "enter"):
            return
        if selected is not None:
            self.dismiss(selected.id)
            return
        self.query_one("#session-offline-dialog", Static).update(
            self._render_content())

    def on_key(self, event: Key) -> None:
        action = navigation_action(event.key)
        if action:
            event.prevent_default()
            event.stop()
            self.nav(action)

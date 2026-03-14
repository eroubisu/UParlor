"""OnlineUsersPanel — 在线用户列表"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ...config import MAX_LINES_ONLINE
from ...state import ModuleStateManager


class OnlineUsersPanel(Widget):
    """在线用户列表面板"""

    def compose(self) -> ComposeResult:
        yield RichLog(id="online-log", wrap=True, highlight=True, markup=True, max_lines=MAX_LINES_ONLINE)

    def _render_users(self, users: list):
        content: RichLog = self.query_one("#online-log", RichLog)
        content.clear()
        content.write(f"[b]在线 ({len(users)})[/b]")
        content.write("─" * 16)
        for u in users:
            if isinstance(u, dict):
                name = u.get("name", str(u))
                count = u.get("count", 1)
                content.write(f"{name}({count})" if count > 1 else name)
            else:
                content.write(str(u))

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event == 'update_users':
            (users,) = args
            self._render_users(users)

    def restore(self, state: ModuleStateManager):
        state.online.set_listener(self._on_state_event)
        if state.online.users:
            self._render_users(state.online.users)

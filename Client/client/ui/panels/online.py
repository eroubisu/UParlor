"""OnlineUsersPanel — 在线用户列表"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ...state import ModuleStateManager


class OnlineUsersPanel(Widget):
    """在线用户列表面板"""

    def compose(self) -> ComposeResult:
        yield RichLog(id="online-log", wrap=True, highlight=True, markup=True, max_lines=200)

    def update_users(self, users: list):
        content: RichLog = self.query_one("#online-log", RichLog)
        content.clear()
        content.write(f"[b]在线 ({len(users)})[/b]")
        content.write("─" * 16)
        for u in users:
            if isinstance(u, dict):
                content.write(u.get("name", str(u)))
            else:
                content.write(str(u))

    def restore(self, state: ModuleStateManager):
        if state.online.users:
            self.update_users(state.online.users)

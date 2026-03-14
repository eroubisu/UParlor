"""LoginPanel — 登录面板"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ..widgets import PromptMixin
from ..widgets.input_bar import InputTextArea
from ..config import MAX_LINES_LOGIN
from ..state import ModuleStateManager


class LoginPanel(PromptMixin, Widget):
    """登录面板：纯简的用户名/密码提示"""

    _prompt_id = "login-prompt"

    def compose(self) -> ComposeResult:
        yield RichLog(id="login-log", wrap=True, highlight=True, markup=True, max_lines=MAX_LINES_LOGIN)
        yield InputTextArea(id="login-prompt", classes="panel-prompt")

    def add_message(self, text: str):
        log: RichLog = self.query_one("#login-log", RichLog)
        log.clear()
        log.write(text)

    def restore(self, state: ModuleStateManager):
        pass

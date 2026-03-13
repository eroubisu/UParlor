"""InputBar — 通用输入栏组件"""

from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Vertical


class InputBar(Vertical):
    """输入框 — 聊天/登录等通用输入栏"""

    def __init__(self, prompt_id: str, title: str = "", **kw):
        super().__init__(**kw)
        self._prompt_id = prompt_id
        if title:
            self.border_title = title

    def compose(self) -> ComposeResult:
        yield Static("", id=self._prompt_id, classes="input-bar-prompt")

    def show_prompt(self, text: str = ""):
        try:
            self.query_one(f"#{self._prompt_id}", Static).update(f"> {text}█")
        except Exception:
            pass

    def update_prompt(self, text: str):
        try:
            self.query_one(f"#{self._prompt_id}", Static).update(f"> {text}█")
        except Exception:
            pass

    def hide_prompt(self):
        try:
            self.query_one(f"#{self._prompt_id}", Static).update("")
        except Exception:
            pass

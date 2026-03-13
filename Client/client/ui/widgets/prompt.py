"""PromptMixin — 输入提示（LoginPanel 专用）"""

from textual.widgets import Static


class PromptMixin:
    """面板输入提示的通用实现"""

    _prompt_id: str  # 子类必须定义

    def show_prompt(self, text: str = ""):
        prompt = self.query_one(f"#{self._prompt_id}", Static)
        prompt.update(f"> {text}█")
        prompt.add_class("visible")

    def update_prompt(self, text: str):
        prompt = self.query_one(f"#{self._prompt_id}", Static)
        prompt.update(f"> {text}█")

    def hide_prompt(self):
        prompt = self.query_one(f"#{self._prompt_id}", Static)
        prompt.update("")
        prompt.remove_class("visible")

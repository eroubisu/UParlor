"""InputBarMixin — InputBar 标准接口 Mixin"""

from .input_bar import InputBar


class InputBarMixin:
    """面板 InputBar 标准接口。

    子类设置类属性:
      _input_bar_id   — InputBar 的 widget id
      _scroll_target_id — 显示输入栏时自动滚动到底部的内容区 widget id（可省略）
    """

    _input_bar_id: str = ""
    _scroll_target_id: str = ""

    def show_prompt(self, text: str = ""):
        try:
            self.query_one(f"#{self._input_bar_id}", InputBar).show_prompt(text)
        except Exception:
            pass

    def update_prompt(self, text: str):
        try:
            self.query_one(f"#{self._input_bar_id}", InputBar).update_prompt(text)
        except Exception:
            pass

    def hide_prompt(self):
        try:
            self.query_one(f"#{self._input_bar_id}", InputBar).hide_prompt()
        except Exception:
            pass

    def show_input_bar(self):
        try:
            self.query_one(f"#{self._input_bar_id}", InputBar).add_class("visible")
        except Exception:
            pass
        if self._scroll_target_id:
            try:
                self.query_one(f"#{self._scroll_target_id}").scroll_end(animate=False)
            except Exception:
                pass

    def hide_input_bar(self):
        try:
            self.query_one(f"#{self._input_bar_id}", InputBar).remove_class("visible")
        except Exception:
            pass

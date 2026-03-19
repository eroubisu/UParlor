"""InputBar — 通用输入栏组件（基于 TextArea 多行输入）"""

from __future__ import annotations

import sys

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import TextArea


def _read_system_clipboard() -> str:
    """读取系统剪贴板文本（Windows ctypes 直读，无外部依赖）"""
    if sys.platform != "win32":
        return ""
    import ctypes
    import ctypes.wintypes as wt
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetClipboardData.restype = wt.HANDLE
    kernel32.GlobalLock.argtypes = [wt.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wt.HANDLE]
    if not user32.OpenClipboard(0):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


class InputTextArea(TextArea):
    """可控文本输入 — 拦截特殊键并通过自定义 Message 通知 Screen

    Textual 的 _on_key 会遍历整个 MRO 链，因此必须用 prevent_default()
    阻止 TextArea 原生处理，再用自定义 Message 替代事件冒泡。

    submit_on_enter=True  → Enter 提交，Shift+Enter 换行
    submit_on_enter=False → Enter 换行，Ctrl+Enter 提交
    """

    class Submit(Message):
        """提交输入"""

    class Escape(Message):
        """退出输入"""

    class TabPress(Message):
        """Tab 补全"""

    class EmptyBackspace(Message):
        """空文本时按 Backspace"""

    def __init__(
        self,
        *,
        submit_on_enter: bool = True,
        **kwargs,
    ):
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("compact", True)
        kwargs.setdefault("tab_behavior", "focus")
        kwargs.setdefault("highlight_cursor_line", False)
        super().__init__(**kwargs)
        self._submit_on_enter = submit_on_enter

    async def _on_key(self, event: events.Key) -> None:
        # Space — 显式处理，确保空格始终可输入
        if event.key == "space":
            event.prevent_default()
            event.stop()
            self.replace(" ", *self.selection)
            return
        # Ctrl+V — 读取系统剪贴板（Windows 上 Textual 不生成 Paste 事件）
        if event.key == "ctrl+v":
            event.prevent_default()
            event.stop()
            text = _read_system_clipboard()
            if text:
                self.replace(text, *self.selection)
            return
        # Escape / Ctrl+[ → 通知 Screen 退出 INSERT
        if event.key in ("escape", "ctrl+left_square_bracket"):
            event.prevent_default()
            event.stop()
            self.post_message(self.Escape())
            return
        # Tab → 通知 Screen 指令补全
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self.post_message(self.TabPress())
            return
        # Enter 提交模式：Enter → 提交，Shift+Enter → 插入换行
        if event.key == "enter" and self._submit_on_enter:
            event.prevent_default()
            event.stop()
            self.post_message(self.Submit())
            return
        if event.key == "shift+enter" and self._submit_on_enter:
            event.prevent_default()
            event.stop()
            self.replace("\n", *self.selection)
            return
        # 多行模式：Ctrl+Enter → 提交
        if event.key == "ctrl+enter" and not self._submit_on_enter:
            event.prevent_default()
            event.stop()
            self.post_message(self.Submit())
            return
        await super()._on_key(event)

    def action_delete_left(self) -> None:
        if not self.text:
            self.post_message(self.EmptyBackspace())
            return
        super().action_delete_left()


class InputBar(Vertical):
    """输入框 — 聊天/AI/物品栏通用输入栏"""

    def __init__(
        self,
        prompt_id: str,
        title: str = "",
        *,
        submit_on_enter: bool = True,
        **kw,
    ):
        super().__init__(**kw)
        self._prompt_id = prompt_id
        self._submit_on_enter = submit_on_enter
        if title:
            self.border_title = title

    def compose(self) -> ComposeResult:
        yield InputTextArea(
            id=self._prompt_id,
            submit_on_enter=self._submit_on_enter,
        )

    def _ta(self) -> InputTextArea | None:
        try:
            return self.query_one(f"#{self._prompt_id}", InputTextArea)
        except Exception:
            return None

    def show_prompt(self, text: str = ""):
        ta = self._ta()
        if ta:
            ta.text = text
            ta.move_cursor(ta.document.end)

    def update_prompt(self, text: str):
        ta = self._ta()
        if ta:
            ta.text = text
            ta.move_cursor(ta.document.end)

    def hide_prompt(self):
        ta = self._ta()
        if ta:
            ta.text = ""

    def get_text(self) -> str:
        ta = self._ta()
        return ta.text if ta else ""

    def focus_input(self):
        ta = self._ta()
        if ta:
            ta.focus()

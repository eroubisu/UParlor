"""Input mode state machine for normal and text-entry operation."""

from __future__ import annotations

from textual.widgets import Static, Input


class InputModeMixin:
    """Vim 风格输入模式管理"""

    def _set_mode(self, mode: str, indicator: str) -> None:
        self._mode = mode
        self.query_one("#mode-indicator", Static).update(f" {indicator} ")

    def _focused_input_is_english(self) -> bool:
        """当前聚焦的输入框是否声明了英文输入法（登录的用户名 / 密码）。"""
        session = getattr(self.engine.active_focused_panel(),
                          "input_session", None)
        return bool(session and session.spec.english_ime)

    def _to_normal(self) -> None:
        if self._mode == 'insert':
            english = self._focused_input_is_english()
            self.engine.leave_insert(preserve=True)
            self.set_focus(None)
            from . import ime
            ime.on_insert_leave(english_ime=english)
        self._set_mode('normal', 'NORMAL')

    def _enter_insert(self, sticky: bool = False):
        if not self.engine.enter_insert(sticky=sticky):
            return
        self._sticky_insert = sticky
        self._set_mode('insert', 'INSERT')
        from . import ime
        ime.on_insert_enter(english_ime=self._focused_input_is_english())

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        if not self._sticky_insert:
            self._to_normal()

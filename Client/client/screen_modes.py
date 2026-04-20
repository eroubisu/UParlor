"""输入模式状态机 — normal / insert / which_key / focus"""

from __future__ import annotations

from textual.widgets import Static, Input


class InputModeMixin:
    """Vim 风格输入模式管理"""

    def _set_mode(self, mode: str, indicator: str) -> None:
        self._mode = mode
        self.query_one("#mode-indicator", Static).update(f" {indicator} ")

    def _to_normal(self) -> None:
        if self._mode == 'insert':
            self.set_focus(None)
            from . import ime
            ime.on_insert_leave()
        elif self._mode == 'which_key':
            from .widgets.which_key import WhichKeyPanel
            self.query_one("#which-key-overlay", WhichKeyPanel).hide()
        self._set_mode('normal', 'NORMAL')

    def _enter_insert(self, sticky: bool = False):
        w = self._get_focused_widget()
        if not w:
            return
        inp = w.get_input_widget() if hasattr(w, 'get_input_widget') else None
        if not inp:
            return
        self._sticky_insert = sticky
        self._set_mode('insert', 'INSERT')
        inp.disabled = False
        inp.focus()
        from . import ime
        ime.on_insert_enter()

    def _enter_which_key(self):
        from .widgets.which_key import WhichKeyPanel
        self.query_one("#which-key-overlay", WhichKeyPanel).show_root()
        self._set_mode('which_key', 'NORMAL')

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self._sticky_insert:
            self._to_normal()

"""KeyboardMixin — 键位处理（on_key 主循环 + 滚动方法）"""

from __future__ import annotations

from textual.widgets import RichLog

from ..vim_mode import Mode
from .layout import navigate, find_pane


class KeyboardMixin:
    """键位处理 Mixin — 提供 on_key 和面板内滚动。"""

    def on_key(self, event) -> None:
        vim = self.vim

        # ── INSERT 模式 ──
        if vim.mode == Mode.INSERT:
            event.prevent_default()
            event.stop()

            if event.key == "escape":
                self.action_enter_normal()
            elif event.key == "enter":
                self._handle_enter()
            elif event.key == "tab":
                self._complete_command()
            elif event.character == "H":
                self._hint_nav('left')
            elif event.character == "L":
                self._hint_nav('right')
            elif event.character == "J":
                self._hint_nav('down')
            elif event.character == "K":
                self._hint_nav('up')
            elif event.key == "backspace":
                if self._input_buffer:
                    self._input_buffer = self._input_buffer[:-1]
                    self._update_panel_prompt(self._input_buffer)
                    self._update_completion()
                else:
                    self._hint_back()
            elif event.key == "space":
                self._input_buffer += " "
                self._update_panel_prompt(self._input_buffer)
                self._update_completion()
            else:
                ch = event.character
                if ch and ch.isprintable():
                    self._input_buffer += ch
                    self._update_panel_prompt(self._input_buffer)
                    self._update_completion()
            return

        # ── NORMAL 模式 ──
        event.prevent_default()
        event.stop()
        key = event.key

        if vim.pending_key == "g":
            vim.pending_key = ""
            if key == "g":
                self._scroll_focused_top()
            return

        # Space 菜单（仅大写 HJKL 导航）
        if self._wk.is_open:
            if key == "escape":
                self._wk.close()
            elif event.character == "J":
                self._wk.nav_down()
            elif event.character == "K":
                self._wk.nav_up()
            elif event.character == "H":
                self._wk.nav_left()
            elif event.character == "L":
                self._wk.nav_right()
            elif key == "enter":
                self._handle_space_enter()
            elif key == "backspace":
                if not self._wk.back():
                    self._wk.close()
            return

        # hjkl 在聚焦窗口内滚动
        if key == "j":
            self._scroll_focused_down()
            return
        if key == "k":
            self._scroll_focused_up()
            return

        # HJKL 窗口焦点切换
        if key == "H":
            new_id = navigate(self._layout_tree, self._focused_pane_id, 'h')
            self._set_focused_pane(new_id)
            return
        if key == "J":
            new_id = navigate(self._layout_tree, self._focused_pane_id, 'j')
            self._set_focused_pane(new_id)
            return
        if key == "K":
            new_id = navigate(self._layout_tree, self._focused_pane_id, 'k')
            self._set_focused_pane(new_id)
            return
        if key == "L":
            new_id = navigate(self._layout_tree, self._focused_pane_id, 'l')
            self._set_focused_pane(new_id)
            return

        # 单键
        if key == "space":
            self._open_space_menu()
        elif key == "i":
            self._enter_insert()
        elif key == "G":
            self._scroll_focused_bottom()
        elif key == "g":
            vim.pending_key = "g"
        elif key == "q":
            self._send_command("/back")
        elif key == "tab":
            self._cycle_channel()
        elif event.character and event.character.isdigit() and event.character != "0":
            self._send_command(f"/{event.character}")

    # ── 滚动 ──

    def _get_focused_log(self) -> RichLog | None:
        pane = find_pane(self._layout_tree, self._focused_pane_id)
        if not pane or not pane.module:
            return None
        widget = self._get_module(pane.module)
        if widget is None:
            return None
        try:
            logs = widget.query(RichLog)
            return logs.first() if logs else None
        except Exception:
            return None

    def _scroll_focused_down(self):
        log = self._get_focused_log()
        if log:
            log.scroll_down(animate=False)

    def _scroll_focused_up(self):
        log = self._get_focused_log()
        if log:
            log.scroll_up(animate=False)

    def _scroll_focused_bottom(self):
        log = self._get_focused_log()
        if log:
            log.scroll_end(animate=False)

    def _scroll_focused_top(self):
        log = self._get_focused_log()
        if log:
            log.scroll_home(animate=False)

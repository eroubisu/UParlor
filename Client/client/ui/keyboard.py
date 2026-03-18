"""KeyboardMixin — 键位处理（on_key 主循环 + 滚动方法）"""

from __future__ import annotations

from textual import events
from textual.widgets import RichLog

from .vim_mode import Mode
from .layout import navigate, find_pane
from ..panels.inventory import InventoryPanel


class KeyboardMixin:
    """键位处理 Mixin — 提供 on_key 和面板内滚动。"""

    def on_paste(self, event: events.Paste) -> None:
        """INSERT 模式粘贴 — TextArea 自行处理，无需拦截"""
        pass

    def on_key(self, event) -> None:
        vim = self.vim

        # ── INSERT 模式 ──
        if vim.mode == Mode.INSERT:
            # TextArea 在 _on_key 中处理可打印字符（并 stop 事件）
            # backspace/delete/cursor 等通过 binding 处理，需冒泡到 App
            # 不要 prevent_default / stop — 让事件继续冒泡
            return

        # ── NORMAL 模式 ──
        event.prevent_default()
        event.stop()
        key = event.key
        if key == "ctrl+left_square_bracket":
            key = "escape"

        if vim.pending_key == "g":
            vim.pending_key = ""
            if key == "g":
                self._scroll_focused_top()
            return

        # 数字前缀累积（vim 风格: 5j = 向下移动5步）
        if key.isdigit() and (key != '0' or vim._count_buffer):
            vim._count_buffer += key
            return

        # Space 菜单（jk 导航，Enter 进入子菜单，Backspace 返回）
        if self._wk.is_open:
            vim._count_buffer = ""
            if key == "escape":
                self._wk.close()
            elif key == "j":
                self._wk.nav_down()
            elif key == "k":
                self._wk.nav_up()
            elif key == "enter":
                self._handle_space_enter()
            elif key == "backspace":
                if not self._wk.back():
                    self._wk.close()
            return

        # 消费数字前缀
        count = vim.consume_count()

        # hjkl 在聚焦窗口内 — 先尝试面板导航，再 fallback 到滚动
        if key == "j":
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_down'):
                try:
                    w.nav_down(count)
                except TypeError:
                    for _ in range(count):
                        w.nav_down()
            else:
                for _ in range(count):
                    self._scroll_focused_down()
            return
        if key == "k":
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_up'):
                try:
                    w.nav_up(count)
                except TypeError:
                    for _ in range(count):
                        w.nav_up()
            else:
                for _ in range(count):
                    self._scroll_focused_up()
            return
        if key == "enter":
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_enter'):
                w.nav_enter()
                if getattr(w, 'wants_insert', False):
                    self._enter_insert()
                return
        if key == "l":
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_tab_next'):
                try:
                    w.nav_tab_next(count)
                except TypeError:
                    for _ in range(count):
                        w.nav_tab_next()
                return
        if key == "h":
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_tab_prev'):
                try:
                    w.nav_tab_prev(count)
                except TypeError:
                    for _ in range(count):
                        w.nav_tab_prev()
                return
        if key == "backspace":
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_back') and w.nav_back():
                return
        if key == "escape":
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_escape') and w.nav_escape():
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
            # 物品栏: i 进入搜索模式
            w = self._get_focused_widget()
            vim.sticky = False
            if isinstance(w, InventoryPanel) and w._mode in ('browse', 'search'):
                w.enter_search()
            self._enter_insert()
        elif key == "I":
            vim.sticky = True
            self._enter_insert()
        elif key == "G":
            self._scroll_focused_bottom()
        elif key == "g":
            vim.pending_key = "g"
        elif key == "tab":
            # 物品栏: tab 切换排序
            w = self._get_focused_widget()
            if isinstance(w, InventoryPanel):
                w.toggle_tab_row()
        elif key == "v":
            w = self._get_focused_widget()
            if isinstance(w, InventoryPanel):
                w.toggle_multi_select()

    # ── 滚动 ──

    def _get_focused_widget(self):
        pane = find_pane(self._layout_tree, self._focused_pane_id)
        if not pane or not pane.module:
            return None
        return self._get_module(pane.module)

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

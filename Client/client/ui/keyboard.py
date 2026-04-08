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

        # 方向键 / Shift+方向键 → hjkl / HJKL（始终生效）
        _ARROW_ALIAS = {
            'left': 'h', 'down': 'j', 'up': 'k', 'right': 'l',
            'shift+left': 'H', 'shift+down': 'J',
            'shift+up': 'K', 'shift+right': 'L',
        }
        key = _ARROW_ALIAS.get(key, key)

        # wasd / WASD → hjkl / HJKL（仅在非输入上下文时）
        if not self._cmd_select_mode and not self._wk.is_open:
            _WASD_ALIAS = {
                'a': 'h', 's': 'j', 'w': 'k', 'd': 'l',
                'A': 'H', 'S': 'J', 'W': 'K', 'D': 'L',
            }
            key = _WASD_ALIAS.get(key, key)

        if vim.pending_key == "g":
            vim.pending_key = ""
            if key == "g":
                self._scroll_focused_top()
            return

        # ── CMD_SELECT 模式（指令栏打开时）──
        if self._cmd_select_mode:
            vim._count_buffer = ""
            _WASD_NAV = {'w': 'up', 's': 'down', 'a': 'left', 'd': 'right'}
            if key == "escape":
                self._close_cmd_select()
            elif key == "J":
                self._hint_nav('down')
            elif key == "K":
                self._hint_nav('up')
            elif key == "H":
                self._hint_nav('left')
            elif key == "L":
                self._hint_nav('right')
            elif key in _WASD_NAV:
                self._hint_nav(_WASD_NAV[key])
            elif key == "enter":
                chain_done = self._hint_enter()
                if chain_done and not self._cmd_select_sticky:
                    self._close_cmd_select()
            elif key == "tab":
                self._hint_tab_complete()
            elif key == "backspace":
                if self._cmd_filter_buf:
                    self._cmd_filter_buf = self._cmd_filter_buf[:-1]
                    self._hint_filter(self._cmd_filter_buf)
                else:
                    self._hint_back()
            elif len(key) == 1 and key.islower():
                self._cmd_filter_buf += key
                self._hint_filter(self._cmd_filter_buf)
            return

        # 数字前缀累积（vim 风格: 5j = 向下移动5步）
        if key.isdigit() and (key != '0' or vim._count_buffer):
            vim._count_buffer += key
            self._update_mode_indicator()
            return

        # Space 菜单（jk 导航，Enter 进入子菜单，Backspace 返回）
        if self._wk.is_open:
            vim._count_buffer = ""
            self._update_mode_indicator()
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
        if count > 1:
            self._update_mode_indicator()

        # hjkl 在聚焦窗口内 — 先尝试面板导航，再 fallback 到滚动
        if key == "j":
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_down'):
                w.nav_down(count)
            else:
                for _ in range(count):
                    self._scroll_focused_down()
            return
        if key == "k":
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_up'):
                w.nav_up(count)
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
        elif key == "p":
            self._open_cmd_select(sticky=False)
        elif key == "P":
            self._open_cmd_select(sticky=True)
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
        return self.get_module(pane.module)

    def _get_focused_log(self) -> RichLog | None:
        pane = find_pane(self._layout_tree, self._focused_pane_id)
        if not pane or not pane.module:
            return None
        widget = self.get_module(pane.module)
        if widget is None:
            return None
        try:
            logs = widget.query(RichLog)
            if logs:
                return logs.first()
        except Exception:
            pass
        # 回退到 VerticalScroll 容器
        try:
            from textual.containers import VerticalScroll
            scrolls = widget.query(VerticalScroll)
            return scrolls.first() if scrolls else None
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

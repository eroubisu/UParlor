"""Inventory 面板 — 视图业务逻辑 (mixin for InventoryPanel)"""

from __future__ import annotations

from .inventory import (
    _BASE_ACTIONS, _SORT_OPTIONS,
    _MODE_BROWSE, _MODE_SEARCH, _MODE_ACTION, _MODE_USE_SUB, _MODE_DETAIL,
    _MODE_INPUT, _MODE_GIFT, _MODE_CONFIRM, _MODE_MULTI_SELECT, _MODE_QUANTITY,
    _MODE_SELECTED,
)


class InventoryViewsMixin:
    """视图业务逻辑 mixin — 导航 + 操作执行 + 搜索/多选"""

    # ── Tab 行切换 ──

    def toggle_tab_row(self):
        """Tab 键: 切换分类 / 排序 / 品质"""
        if self._mode not in (_MODE_BROWSE, _MODE_SEARCH, _MODE_MULTI_SELECT, _MODE_SELECTED):
            return
        self._tab_row = (self._tab_row + 1) % 3
        if self._tab_row == 0:
            items = self._build_cat_items()
            for i, (v, _) in enumerate(items):
                if v == self._filter_tab:
                    self._cat_cursor = i
                    break
        elif self._tab_row == 2:
            items = self._build_quality_items()
            for i, (v, _) in enumerate(items):
                if v == self._quality_filter:
                    self._quality_cursor = i
                    break
        self._render_header()

    # ── 导航接口 ──

    def nav_tab_next(self):
        """l 键: 在当前标签行内向右切换"""
        if self._mode not in (_MODE_BROWSE, _MODE_SEARCH, _MODE_MULTI_SELECT, _MODE_SELECTED):
            return
        if self._tab_row == 0:
            items = self._build_cat_items()
            if not items:
                return
            self._cat_cursor = (self._cat_cursor + 1) % len(items)
            self._filter_tab = items[self._cat_cursor][0]
        elif self._tab_row == 1:
            self._sort_cursor = (self._sort_cursor + 1) % (2 * len(_SORT_OPTIONS))
        else:
            items = self._build_quality_items()
            if not items:
                return
            self._quality_cursor = (self._quality_cursor + 1) % len(items)
            self._quality_filter = items[self._quality_cursor][0]
        self._apply_filter()
        self._scroll_offset = 0
        self._render_header()
        self._refresh_content()

    def nav_tab_prev(self):
        """h 键: 在当前标签行内向左切换"""
        if self._mode not in (_MODE_BROWSE, _MODE_SEARCH, _MODE_MULTI_SELECT, _MODE_SELECTED):
            return
        if self._tab_row == 0:
            items = self._build_cat_items()
            if not items:
                return
            self._cat_cursor = (self._cat_cursor - 1) % len(items)
            self._filter_tab = items[self._cat_cursor][0]
        elif self._tab_row == 1:
            self._sort_cursor = (self._sort_cursor - 1) % (2 * len(_SORT_OPTIONS))
        else:
            items = self._build_quality_items()
            if not items:
                return
            self._quality_cursor = (self._quality_cursor - 1) % len(items)
            self._quality_filter = items[self._quality_cursor][0]
        self._apply_filter()
        self._scroll_offset = 0
        self._render_header()
        self._refresh_content()

    def nav_down(self, count=1):
        if self._mode in (_MODE_BROWSE, _MODE_SEARCH, _MODE_MULTI_SELECT, _MODE_SELECTED):
            if self._filtered:
                self._cursor = (self._cursor + count) % len(self._filtered)
        elif self._mode == _MODE_ACTION:
            item = self._filtered[self._cursor] if self._filtered else None
            actions = self._get_item_actions(item) if item else _BASE_ACTIONS
            self._action_cursor = (self._action_cursor + count) % len(actions)
        elif self._mode == _MODE_USE_SUB:
            if self._use_methods:
                self._use_cursor = (self._use_cursor + count) % len(self._use_methods)
        elif self._mode == _MODE_GIFT:
            if self._gift_friends:
                self._gift_cursor = (self._gift_cursor + count) % len(self._gift_friends)
                self._ensure_gift_scroll()
        self._ensure_scroll()
        self._refresh_content()

    def nav_up(self, count=1):
        if self._mode in (_MODE_BROWSE, _MODE_SEARCH, _MODE_MULTI_SELECT, _MODE_SELECTED):
            if self._filtered:
                self._cursor = (self._cursor - count) % len(self._filtered)
        elif self._mode == _MODE_ACTION:
            item = self._filtered[self._cursor] if self._filtered else None
            actions = self._get_item_actions(item) if item else _BASE_ACTIONS
            self._action_cursor = (self._action_cursor - count) % len(actions)
        elif self._mode == _MODE_USE_SUB:
            if self._use_methods:
                self._use_cursor = (self._use_cursor - count) % len(self._use_methods)
        elif self._mode == _MODE_GIFT:
            if self._gift_friends:
                self._gift_cursor = (self._gift_cursor - count) % len(self._gift_friends)
                self._ensure_gift_scroll()
        self._ensure_scroll()
        self._refresh_content()

    def nav_enter(self):
        if self._mode in (_MODE_BROWSE, _MODE_SEARCH):
            if self._filtered:
                self._batch_mode = False
                self._action_cursor = 0
                self._mode = _MODE_ACTION
        elif self._mode == _MODE_MULTI_SELECT:
            if self._filtered:
                item = self._filtered[self._cursor]
                max_qty = item.get('count', 1)
                self._input_label = f"数量 (1-{max_qty})"
                self._wants_insert = True
                self._mode = _MODE_QUANTITY
        elif self._mode == _MODE_SELECTED:
            if self._filtered:
                self._batch_mode = True
                self._action_cursor = 0
                self._mode = _MODE_ACTION
        elif self._mode == _MODE_ACTION:
            self._execute_base_action()
        elif self._mode == _MODE_USE_SUB:
            self._execute_use_method()
        elif self._mode == _MODE_GIFT:
            self._execute_gift()
        elif self._mode == _MODE_CONFIRM:
            self._execute_confirm()
        self._ensure_scroll()
        self._refresh_content()

    def nav_back(self) -> bool:
        if self._mode == _MODE_SEARCH and not self._wants_insert:
            self._search_query = ""
            self._mode = _MODE_BROWSE
            self._apply_filter()
            self._scroll_offset = 0
            self._render_header()
            self._refresh_content()
            return True
        if self._mode == _MODE_SELECTED:
            self._selections.clear()
            self._batch_mode = False
            self._mode = _MODE_BROWSE
            self._apply_filter()
            self._scroll_offset = 0
            self._refresh_content()
            return True
        if self._mode == _MODE_MULTI_SELECT:
            self._selections.clear()
            self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        if self._mode == _MODE_INPUT:
            return False
        if self._mode == _MODE_GIFT:
            return False
        if self._mode == _MODE_USE_SUB:
            self._mode = _MODE_ACTION
            self._refresh_content()
            return True
        if self._mode == _MODE_CONFIRM:
            self._mode = _MODE_ACTION
            self._refresh_content()
            return True
        if self._mode == _MODE_ACTION:
            if self._batch_mode:
                self._mode = _MODE_SELECTED
            else:
                self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        if self._mode == _MODE_DETAIL:
            if self._batch_mode:
                self._mode = _MODE_SELECTED
            else:
                self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        return False

    def nav_escape(self) -> bool:
        if self._mode == _MODE_INPUT:
            self._wants_insert = False
            self._pending_cmds = []
            self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        if self._mode == _MODE_GIFT:
            self._wants_insert = False
            self._gift_query = ""
            if self._batch_mode:
                self._mode = _MODE_SELECTED
                self._apply_filter()
            else:
                self._mode = _MODE_ACTION
            self.hide_input_bar()
            self._refresh_content()
            return True
        if self._mode == _MODE_SEARCH:
            self._wants_insert = False
            self._search_query = ""
            self._mode = _MODE_BROWSE
            self._apply_filter()
            self.hide_input_bar()
            self._refresh_content()
            return True
        if self._mode == _MODE_MULTI_SELECT:
            self._selections.clear()
            self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        if self._mode == _MODE_QUANTITY:
            self._wants_insert = False
            self.hide_input_bar()
            self._mode = _MODE_MULTI_SELECT
            self._refresh_content()
            return True
        if self._mode == _MODE_SELECTED:
            self._selections.clear()
            self._batch_mode = False
            self._mode = _MODE_BROWSE
            self._apply_filter()
            self._refresh_content()
            return True
        if self._mode != _MODE_BROWSE:
            self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        if self._filter_tab != 'all' or self._quality_filter != 'all' or self._sort_cursor != 0 or self._search_query:
            self._filter_tab = 'all'
            self._quality_filter = 'all'
            self._sort_cursor = 0
            self._search_query = ''
            self._tab_row = 0
            self._cat_cursor = 0
            self._quality_cursor = 0
            self._cursor = 0
            self._scroll_offset = 0
            self._apply_filter()
            self._render_header()
            self._refresh_content()
            return True
        return False

    # ── 搜索模式 ──

    def enter_search(self):
        self._mode = _MODE_SEARCH
        self._search_query = ""
        self._wants_insert = True
        self._apply_filter()
        self._refresh_content()

    # ── 多选模式 ──

    def toggle_multi_select(self):
        """v 键: BROWSE→MULTI_SELECT / MULTI_SELECT→SELECTED / SELECTED→BROWSE"""
        if self._mode in (_MODE_BROWSE, _MODE_SEARCH):
            self._selections.clear()
            self._mode = _MODE_MULTI_SELECT
            self._refresh_content()
        elif self._mode == _MODE_MULTI_SELECT:
            if self._selections:
                self._cursor = 0
                self._scroll_offset = 0
                self._mode = _MODE_SELECTED
                self._apply_filter()
            else:
                self._mode = _MODE_BROWSE
            self._refresh_content()
        elif self._mode == _MODE_SELECTED:
            self._selections.clear()
            self._batch_mode = False
            self._mode = _MODE_BROWSE
            self._apply_filter()
            self._refresh_content()

    # ── InputBar 回调 ──

    def on_search_change(self, text: str):
        if self._mode == _MODE_SEARCH:
            self._search_query = text.strip()
            self._cursor = 0
            self._scroll_offset = 0
            self._apply_filter()
            self._refresh_content()
        elif self._mode == _MODE_GIFT:
            self._gift_query = text.strip()
            self._gift_cursor = 0
            self._gift_scroll = 0
            self._update_gift_friends()
            self._refresh_content()

    def on_input_submit(self, text: str):
        if self._mode == _MODE_QUANTITY:
            self._wants_insert = False
            self.hide_input_bar()
            item = self._filtered[self._cursor]
            key = self._item_key(item)
            max_qty = item.get('count', 1)
            try:
                qty = max(0, min(int(text.strip()), max_qty))
            except ValueError:
                qty = 0
            if qty > 0:
                self._selections[key] = qty
            else:
                self._selections.pop(key, None)
            self._mode = _MODE_MULTI_SELECT
            self._refresh_content()
        elif self._mode == _MODE_SEARCH:
            self._search_query = text.strip()
            self._wants_insert = False
            self._cursor = 0
            self._scroll_offset = 0
            self._apply_filter()
            self.hide_input_bar()
            self._refresh_content()
        elif self._mode == _MODE_INPUT:
            self._wants_insert = False
            self._confirm_label = f"{self._input_label} '{text}'"
            self._confirm_cmds = list(self._pending_cmds) + [text, '/y']
            self._pending_cmds = []
            self._mode = _MODE_CONFIRM
            self._refresh_content()
        elif self._mode == _MODE_GIFT:
            self._execute_gift()

    def cancel_input(self):
        if self._mode == _MODE_QUANTITY:
            self._wants_insert = False
            self.hide_input_bar()
            self._mode = _MODE_MULTI_SELECT
            self._refresh_content()
        elif self._mode == _MODE_INPUT:
            self._wants_insert = False
            self._pending_cmds = []
            self._mode = _MODE_USE_SUB
            self._refresh_content()
        elif self._mode == _MODE_SEARCH:
            self._wants_insert = False
            self._search_query = ""
            self._apply_filter()
            self._refresh_content()
        elif self._mode == _MODE_GIFT:
            self._wants_insert = False
            self._gift_query = ""
            self._mode = _MODE_ACTION
            self._refresh_content()

    # ── 操作执行 ──

    def _execute_base_action(self):
        if not self._filtered or self._cursor >= len(self._filtered):
            return
        item = self._filtered[self._cursor]
        actions = self._get_item_actions(item)
        action_id, _ = actions[self._action_cursor]
        if self._batch_mode:
            self._execute_batch_action(action_id)
            return

        if action_id == 'unequip':
            slot = item.get('equipped', '')
            if slot:
                try:
                    self.app.network.send({'type': 'unequip', 'slot': slot})
                except Exception:
                    pass
            self._mode = _MODE_BROWSE
        elif action_id == 'use':
            use_methods = item.get('use_methods', [])
            self._use_methods = use_methods
            self._use_cursor = 0
            self._mode = _MODE_USE_SUB
        elif action_id == 'gift':
            self._gift_item_id = self._item_key(item)
            self._gift_cursor = 0
            self._gift_scroll = 0
            self._gift_query = ""
            self._update_gift_friends()
            self._wants_insert = True
            self._mode = _MODE_GIFT
        elif action_id == 'info':
            self._mode = _MODE_DETAIL
        elif action_id == 'drop':
            self._send_command(f"/drop {self._item_key(item)} y")
            self._mode = _MODE_BROWSE

    def _execute_batch_action(self, action_id: str):
        """批量操作执行"""
        if action_id == 'use':
            for key, qty in list(self._selections.items()):
                item = next((i for i in self._items if self._item_key(i) == key), None)
                if item and item.get('use_methods'):
                    mid = item['use_methods'][0]['id']
                    for _ in range(qty):
                        self._send_command(f"/use {key} {mid}")
            self._selections.clear()
            self._batch_mode = False
            self._mode = _MODE_BROWSE
        elif action_id == 'gift':
            self._gift_cursor = 0
            self._gift_scroll = 0
            self._gift_query = ""
            self._update_gift_friends()
            self._wants_insert = True
            self._mode = _MODE_GIFT
        elif action_id == 'info':
            self._mode = _MODE_DETAIL
        elif action_id == 'drop':
            for key, qty in list(self._selections.items()):
                self._send_command(f"/drop {key} y {qty}")
            self._selections.clear()
            self._batch_mode = False
            self._mode = _MODE_BROWSE

    def _execute_use_method(self):
        if not self._use_methods or not self._filtered:
            return
        item = self._filtered[self._cursor]
        method = self._use_methods[self._use_cursor]
        item_key = self._item_key(item)
        input_prompt = method.get('input_prompt')
        if input_prompt:
            self._pending_cmds = [f"/use {item_key} {method['id']}"]
            self._input_label = input_prompt
            self._wants_insert = True
            self._mode = _MODE_INPUT
        else:
            self._send_command(f"/use {item_key} {method['id']}")
            self._mode = _MODE_BROWSE
            self._action_cursor = 0

    def _execute_gift(self):
        if not self._gift_friends:
            return
        if self._gift_cursor >= len(self._gift_friends):
            return
        target = self._gift_friends[self._gift_cursor]
        self._wants_insert = False
        self._gift_query = ""
        self.hide_input_bar()
        if self._batch_mode:
            for key, qty in list(self._selections.items()):
                for _ in range(qty):
                    self._send_command(f"/gift {key}")
                    self._send_command(target)
            self._selections.clear()
            self._batch_mode = False
            self._mode = _MODE_BROWSE
        else:
            self._send_command(f"/gift {self._gift_item_id}")
            self._send_command(target)
            self._mode = _MODE_BROWSE

    def _execute_confirm(self):
        for cmd in self._confirm_cmds:
            self._send_command(cmd)
        self._confirm_cmds = []
        self._confirm_label = ''
        self._selections.clear()
        self._batch_mode = False
        self._mode = _MODE_BROWSE

    def _send_command(self, cmd: str):
        try:
            self.app.send_command(cmd)
        except Exception:
            pass

    def _update_gift_friends(self):
        if not self._state_mgr:
            self._gift_friends = []
            return
        friends = list(self._state_mgr.online.friends)
        q = self._gift_query.lower()
        if q:
            friends = [f for f in friends if q in f.lower()]
        self._gift_friends = friends

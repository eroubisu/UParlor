"""WhichKeyPanel — Space 菜单浮窗（标签页形式）"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from ..widgets import TabMenuBase


class WhichKeyPanel(TabMenuBase):
    """Space 菜单：继承 TabMenuBase，items 为 tuple (name, desc[, sub_items])"""

    _tabs_widget_id = "wk-tabs"
    _content_widget_id = "wk-content"

    def __init__(self, **kw):
        super().__init__(id="which-key-overlay", **kw)
        self._visible = False
        self.border_title = "菜单"

    def compose(self) -> ComposeResult:
        yield Static("", id="wk-tabs", classes="hint-tabs")
        yield Static("", id="wk-content", classes="hint-content")

    # ── TabMenuBase 钩子 ──

    def _item_name(self, item) -> str:
        return item[0]

    def _item_desc(self, item) -> str:
        return item[1] if len(item) > 1 else ""

    def _item_sub(self, item) -> list | None:
        if len(item) >= 3 and item[2]:
            return item[2]
        return None

    def _make_sub_tab(self, item) -> tuple[str, list]:
        return (item[0], item[2])

    # ── 公共接口 ──

    def open(self, tabs: list[tuple[str, list]]):
        """打开菜单，设置顶级标签页"""
        self._visible = True
        # 直接存储数据，不在隐藏状态下渲染（此时宽度为 0）
        self._tabs = tabs
        if self._active_tab >= len(tabs):
            self._active_tab = 0
        self._selected_idx = 0
        self._scroll_offset = 0
        self._nav_stack = []
        self.add_class("visible")
        self.call_after_refresh(self._refresh_display)

    def close(self):
        """关闭菜单"""
        self._visible = False
        self._nav_stack.clear()
        self.remove_class("visible")

    @property
    def is_open(self) -> bool:
        return self._visible

    @property
    def active_tab_name(self) -> str:
        if self._tabs and self._active_tab < len(self._tabs):
            return self._tabs[self._active_tab][0]
        return ""

    @property
    def selected_index(self) -> int:
        return self._selected_idx

    # ── enter 覆盖：返回 (tab_name, item_index) 而非 item 对象 ──

    def enter(self) -> tuple[str, int] | None:
        items = self._current_items()
        if not items or self._selected_idx >= len(items):
            return None
        item = items[self._selected_idx]
        sub = self._item_sub(item)
        if sub:
            self._push_stack()
            tab_name, sub_items = self._make_sub_tab(item)
            self._tabs = [(tab_name, sub_items)]
            self._active_tab = 0
            self._selected_idx = 0
            self._scroll_offset = 0
            self._refresh_display()
            return None
        tab_name = self._tabs[self._active_tab][0] if self._tabs else ""
        return (tab_name, self._selected_idx)

    # ── 数据刷新 ──

    def refresh_items(self, tab_idx: int, items: list[tuple[str, str]]):
        """刷新指定标签页的项目列表"""
        if 0 <= tab_idx < len(self._tabs):
            name = self._tabs[tab_idx][0]
            self._tabs[tab_idx] = (name, items)
            self._refresh_display()

    def refresh_current_items(self, items: list[tuple[str, str]]):
        """刷新当前标签页的项目列表"""
        if self._tabs and self._active_tab < len(self._tabs):
            name = self._tabs[self._active_tab][0]
            self._tabs[self._active_tab] = (name, items)
            self._refresh_display()

"""WhichKeyPanel — Space 菜单浮窗（列表形式，Enter 进入子菜单）"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from ..config import COLOR_CMD
from ..widgets import TabMenuBase


class WhichKeyPanel(TabMenuBase):
    """Space 菜单：继承 TabMenuBase，单列表 + 子菜单钻入。

    items 为 tuple (name, desc[, sub_items[, key]])
    """

    _tabs_widget_id = "wk-title"
    _content_widget_id = "wk-content"

    def __init__(self, **kw):
        super().__init__(id="which-key-overlay", **kw)
        self._visible = False
        self.border_title = "菜单"

    def compose(self) -> ComposeResult:
        yield Static("", id="wk-title")
        yield Static("", id="wk-content", classes="hint-content")

    # ── TabMenuBase 钩子 ──

    def _item_name(self, item) -> str:
        key = item[3] if len(item) > 3 and item[3] else None
        name = item[0]
        if key:
            return f"[{COLOR_CMD}]{key}[/] {name}"
        return name

    def _item_desc(self, item) -> str:
        return item[1] if len(item) > 1 else ""

    def _item_sub(self, item) -> list | None:
        if len(item) >= 3 and item[2]:
            return item[2]
        return None

    def _make_sub_tab(self, item) -> tuple[str, list]:
        return (item[0], item[2])

    # ── 覆盖：根级隐藏标题栏，子菜单显示面包屑 ──

    def _update_widgets(self, tab_text, content):
        try:
            title_w = self.query_one("#wk-title", Static)
            if self._nav_stack:
                title_w.update(tab_text)
                title_w.display = True
            else:
                title_w.update("")
                title_w.display = False
        except Exception:
            pass
        try:
            self.query_one("#wk-content", Static).update(content)
        except Exception:
            pass

    # ── 禁用 h/l 切换标签 ──

    def nav_left(self):
        pass

    def nav_right(self):
        pass

    # ── 公共接口 ──

    def key_select(self, key: str) -> bool:
        """按快捷键选中项目。返回 True 表示命中。"""
        items = self._current_items()
        for i, item in enumerate(items):
            item_key = item[3] if len(item) > 3 else None
            if item_key and item_key == key:
                self._selected_idx = i
                return True
        return False

    def open(self, items: list[tuple]):
        """打开菜单，items 为顶级列表项（可含子菜单）"""
        self._visible = True
        self._tabs = [("菜单", items)]
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
    def selected_index(self) -> int:
        return self._selected_idx

    # ── enter 覆盖：返回 (category_name, item_index) ──

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
        # 叶子节点 — 返回当前所在分类名 + 项目索引
        cat_name = self._tabs[0][0] if self._tabs else ""
        return (cat_name, self._selected_idx)

    # ── 数据刷新 ──

    def refresh_category_items(self, cat_name: str, items: list[tuple[str, str]]):
        """刷新指定分类的子菜单项目"""
        if not self._nav_stack:
            return
        if self._tabs and self._tabs[0][0] == cat_name:
            self._tabs[0] = (cat_name, items)
            self._refresh_display()

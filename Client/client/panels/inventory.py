"""InventoryPanel — 物品栏面板

功能:
  全部物品平铺显示，支持排序/筛选/搜索
  Tab 切换标签行（分类 / 排序 / 品质）
  i 进入搜索模式（INSERT）
  v 多选: 选物品+数量 → v 进入已选页面 → 批量操作

状态机:
  BROWSE       — j/k 移动物品光标，Enter 打开操作菜单
  SEARCH       — INSERT 模式搜索物品
  MULTI_SELECT — 多选模式，Enter 选择+输入数量，v 进入已选页面
  QUANTITY     — INSERT 模式输入选择数量
  SELECTED     — 已选物品页面，Enter 打开批量操作菜单
  ACTION       — j/k 在操作间移动，Enter 执行
  USE_SUB      — 物品多种使用方式子菜单
  DETAIL       — 显示物品描述
  INPUT        — 需要文字输入的操作
  GIFT         — 赠送物品时搜索好友
  CONFIRM      — 丢弃物品的确认提示
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static
from textual.widget import Widget

from ..state import ModuleStateManager
from ..widgets.input_bar import InputBar
from ..widgets.prompt import InputBarMixin
from ..data import QUALITY_LABELS as _QUALITY_LABELS
from ._mixins.inventory import (
    _InventoryRenderMixin, _BASE_ACTIONS, _FILTER_TABS, _FILTER_LABELS, _SORT_OPTIONS,
    _QUALITY_ALL, _MAX_GIFT_VISIBLE,
    _MODE_BROWSE, _MODE_ACTION, _MODE_USE_SUB, _MODE_DETAIL,
    _MODE_INPUT, _MODE_GIFT, _MODE_CONFIRM, _MODE_QUANTITY,
    _MODE_SELECTED,
)
from ._mixins.inventory_views import _InventoryViewsMixin


class InventoryPanel(InputBarMixin, _InventoryViewsMixin, _InventoryRenderMixin, Widget):
    """物品栏面板：三标签行(分类/排序/品质) + j/k 导航 + Enter 操作"""

    _input_bar_id = "inventory-input-bar"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._mode: str = _MODE_BROWSE
        self._cursor: int = 0
        self._scroll_offset: int = 0
        self._items: list[dict] = []
        self._filtered: list[dict] = []
        self._gold: int = 0
        # 标签行: 0=分类, 1=排序, 2=品质
        self._tab_row: int = 0
        # 分类筛选
        self._filter_tab: str = "all"
        self._cat_cursor: int = 0
        # 排序 (flat cursor: 0..2N-1, even=asc odd=desc)
        self._sort_cursor: int = 0
        # 品质筛选
        self._quality_filter: str = "all"
        self._quality_cursor: int = 0
        # 搜索
        self._search_query: str = ""
        # ACTION 模式
        self._action_cursor: int = 0
        # USE_SUB 模式
        self._use_methods: list[dict] = []
        self._use_cursor: int = 0
        # INPUT 模式
        self._wants_insert: bool = False
        self._pending_cmds: list[str] = []
        self._input_label: str = ''
        # GIFT 模式（赠送选择好友）
        self._gift_item_id: str = ''
        self._gift_cursor: int = 0
        self._gift_scroll: int = 0
        self._gift_query: str = ""
        self._gift_friends: list[str] = []
        # CONFIRM 模式
        self._confirm_label: str = ''
        self._confirm_cmds: list[str] = []
        # 多选/已选
        self._selections: dict = {}  # item_key → quantity
        self._batch_mode: bool = False
        # 状态管理器引用
        self._state_mgr: ModuleStateManager | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="inventory-header", markup=True)
        yield Static(id="inventory-content")
        yield InputBar(prompt_id="inventory-prompt", id="inventory-input-bar")

    def on_mount(self) -> None:
        try:
            self.query_one("#inventory-input-bar", InputBar).remove_class("visible")
        except Exception:
            pass

    # ── 属性 ──

    @property
    def wants_insert(self) -> bool:
        return self._wants_insert

    # ── 可见高度 ──

    def _visible_height(self) -> int:
        try:
            w = self.query_one("#inventory-content", Static)
            h = w.scrollable_content_region.height
            return h if h > 0 else 10
        except Exception:
            return 10

    # ── 筛选行数据 ──

    def _build_cat_items(self) -> list[tuple[str, str]]:
        """构建分类筛选条目: [(value, label), ...]"""
        items: list[tuple[str, str]] = [('all', '全部')]
        cats = {i.get('category', '') for i in self._items}
        for t in _FILTER_TABS[1:]:
            if t in cats:
                items.append((t, _FILTER_LABELS[t]))
        return items

    def _build_quality_items(self) -> list[tuple[str, str]]:
        """构建品质筛选条目: [(value, label), ...]"""
        items: list[tuple[str, str]] = [('all', '全部')]
        quals = {i.get('quality', 0) for i in self._items}
        for qv in _QUALITY_ALL[1:]:
            if int(qv) in quals:
                items.append((qv, _QUALITY_LABELS[qv]))
        return items

    # ── 筛选/排序/搜索 ──

    def _apply_filter(self):
        items = self._items
        # 分类筛选
        if self._filter_tab != "all":
            items = [i for i in items if i.get('category') == self._filter_tab]
        # 品质筛选
        if self._quality_filter != "all":
            qval = int(self._quality_filter)
            items = [i for i in items if i.get('quality', 0) == qval]
        # 搜索
        q = self._search_query.lower()
        if q:
            items = [i for i in items if q in i.get('name', '').lower()]
        # 排序 (从 flat cursor 推导)
        sort_key = _SORT_OPTIONS[self._sort_cursor // 2][0]
        rev = (self._sort_cursor % 2 == 1)
        if sort_key == "name":
            items.sort(key=lambda i: i.get('name', ''), reverse=rev)
        elif sort_key == "count":
            items.sort(key=lambda i: i.get('count', 0), reverse=rev)
        elif sort_key == "category":
            items.sort(key=lambda i: (i.get('category', ''), i.get('name', '')), reverse=rev)
        elif sort_key == "quality":
            items.sort(key=lambda i: i.get('quality', 0), reverse=rev)
        elif sort_key == "equipped":
            items.sort(key=lambda i: (1 if i.get('equipped') else 0), reverse=rev)
        # 已选模式: 只显示已选物品
        if self._mode == _MODE_SELECTED or self._batch_mode:
            items = [i for i in items if self._item_key(i) in self._selections]
        self._filtered = items
        if self._cursor >= len(self._filtered):
            self._cursor = max(0, len(self._filtered) - 1)

    def _ensure_scroll(self):
        if not self._filtered:
            return
        vh = self._visible_height()
        extra = 0
        if self._mode == _MODE_ACTION:
            item = self._filtered[self._cursor] if self._filtered and self._cursor < len(self._filtered) else None
            actions = self._get_item_actions(item) if item else _BASE_ACTIONS
            extra = len(actions)
        elif self._mode == _MODE_USE_SUB:
            extra = max(1, len(self._use_methods))
        elif self._mode == _MODE_GIFT:
            n = len(self._gift_friends)
            extra = min(n, _MAX_GIFT_VISIBLE) + 1 if n else 1
        elif self._mode in (_MODE_CONFIRM, _MODE_DETAIL, _MODE_INPUT, _MODE_QUANTITY):
            extra = 1
        need = 1 + extra
        avail_vh = max(1, vh)
        if self._cursor < self._scroll_offset:
            self._scroll_offset = self._cursor
        elif self._cursor + need > self._scroll_offset + avail_vh:
            self._scroll_offset = self._cursor + need - avail_vh
        self._scroll_offset = max(0, self._scroll_offset)

    def _ensure_gift_scroll(self):
        if self._gift_cursor < self._gift_scroll:
            self._gift_scroll = self._gift_cursor
        elif self._gift_cursor >= self._gift_scroll + _MAX_GIFT_VISIBLE:
            self._gift_scroll = self._gift_cursor - _MAX_GIFT_VISIBLE + 1

    def on_resize(self, event) -> None:
        self._render_header()

    # ── 物品工具 ──

    def _item_key(self, item: dict) -> str:
        """构造 item_id:quality 键"""
        q = item.get('quality', 0)
        return f"{item['id']}:{q}"

    def _get_item_actions(self, item: dict) -> list[tuple[str, str]]:
        """返回物品的可用操作列表（已装备物品只有"卸下"和"详情"）"""
        if item.get('equipped'):
            return [('unequip', '卸下'), ('info', '详情')]
        return _BASE_ACTIONS

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event == 'update_inventory':
            self._sync_from_state()

    def _sync_from_state(self):
        st = self._state
        self._items = list(st.items)
        self._gold = st.gold
        self._apply_filter()
        self.call_after_refresh(self._refresh_all)

    def _update_gold_subtitle(self):
        try:
            self.parent.border_subtitle = f"{self._gold}G"
        except Exception:
            pass

    def _refresh_all(self):
        self._render_header()
        self._refresh_content()

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        self._state = state.inventory
        st = self._state
        self._filter_tab = st.filter_tab
        self._quality_filter = st.quality_filter
        self._sort_cursor = st.sort_cursor
        self._tab_row = st.tab_row
        self._cursor = st.cursor
        cat_items = self._build_cat_items()
        self._cat_cursor = next(
            (i for i, (v, _) in enumerate(cat_items) if v == self._filter_tab), 0)
        qual_items = self._build_quality_items()
        self._quality_cursor = next(
            (i for i, (v, _) in enumerate(qual_items) if v == self._quality_filter), 0)
        self._state.add_listener(self._on_state_event)
        self._sync_from_state()

    def on_unmount(self):
        if self._state_mgr:
            self._state_mgr.inventory.remove_listener(self._on_state_event)
            st = self._state_mgr.inventory
            st.cursor = self._cursor
            st.filter_tab = self._filter_tab
            st.quality_filter = self._quality_filter
            st.sort_cursor = self._sort_cursor
            st.tab_row = self._tab_row

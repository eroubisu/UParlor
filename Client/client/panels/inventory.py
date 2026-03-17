"""InventoryPanel — 物品栏面板

功能:
  全部物品平铺显示，支持排序/筛选/搜索
  Tab 切换标签行（分类 / 排序 / 品质）
  分类行: h/l 切换分类筛选
  排序行: h/l 在 △▽ 间移动，光标位置决定排序方式和方向
  品质行: h/l 切换品质筛选
  i 进入搜索模式（INSERT）
  v 多选: 选物品+数量 → v 进入已选页面 → 批量操作

品质标签（仿 Dwarf Fortress）:
  0 普通（无标记）  1 -精良-  2 +优秀+  3 *卓越*  4 =史诗=  5 !传奇!

状态机:
  BROWSE       — j/k 移动物品光标，Enter 打开操作菜单
  SEARCH       — INSERT 模式搜索物品（提交后 backspace 可回退）
  MULTI_SELECT — 多选模式，Enter 选择+输入数量，v 进入已选页面
  QUANTITY     — INSERT 模式输入选择数量
  SELECTED     — 已选物品页面，Enter 打开批量操作菜单
  ACTION       — j/k 在四个固定操作间移动，Enter 执行
  USE_SUB      — 物品有多种使用方式时的子菜单
  DETAIL       — 显示物品描述
  INPUT        — 需要文字输入的操作（如改名卡），进入 INSERT 模式
  GIFT         — 赠送物品时搜索好友，INSERT 模式
  CONFIRM      — 丢弃物品的确认提示
"""

from __future__ import annotations

from rich.cells import cell_len
from textual.app import ComposeResult
from textual.widgets import Static
from textual.widget import Widget

from ..config import (
    COLOR_FG_PRIMARY,
    COLOR_FG_SECONDARY,
    COLOR_FG_TERTIARY,
    COLOR_ACCENT,
    COLOR_BORDER_LIGHT,
    COLOR_HINT_TAB_ACTIVE, COLOR_HINT_TAB_DIM,
)
from ..state import ModuleStateManager
from ..widgets.helpers import update_tab_header
from ..widgets.input_bar import InputBar
from ..widgets.prompt import InputBarMixin

# 四个固定操作（每个物品都有）
_BASE_ACTIONS: list[tuple[str, str]] = [
    ('use',  '使用'),
    ('gift', '赠送'),
    ('info', '详情'),
    ('drop', '丢弃'),
]

_MODE_BROWSE  = 'browse'
_MODE_SEARCH  = 'search'
_MODE_ACTION  = 'action'
_MODE_USE_SUB = 'use_sub'
_MODE_DETAIL  = 'detail'
_MODE_INPUT   = 'input'
_MODE_GIFT         = 'gift'
_MODE_CONFIRM      = 'confirm'
_MODE_MULTI_SELECT = 'multi_select'
_MODE_QUANTITY     = 'quantity'
_MODE_SELECTED     = 'selected'

# 分类筛选标签
_FILTER_TABS = ["all", "consumable", "prop", "equipment", "material", "currency", "special"]
_FILTER_LABELS = {
    "all": "全部",
    "consumable": "消耗",
    "prop": "道具",
    "equipment": "装备",
    "material": "材料",
    "currency": "货币",
    "special": "特殊",
}

# 品质定义（仿 Dwarf Fortress）
_QUALITY_MARKERS = {
    0: ('', ''),
    1: ('-', '-'),
    2: ('+', '+'),
    3: ('*', '*'),
    4: ('=', '='),
    5: ('!', '!'),
}

_QUALITY_LABELS = {
    "all": "全部",
    "0": "普通",
    "1": "-精良-",
    "2": "+优秀+",
    "3": "*卓越*",
    "4": "=史诗=",
    "5": "!传奇!",
}

_QUALITY_ALL = ["all", "0", "1", "2", "3", "4", "5"]

# 排序方式
_SORT_OPTIONS = [("name", "名称"), ("count", "数量"), ("category", "分类"), ("quality", "品质")]

_MAX_GIFT_VISIBLE = 5


def _quality_name(name: str, quality: int) -> str:
    """给物品名添加品质标记"""
    pre, suf = _QUALITY_MARKERS.get(quality, ('', ''))
    if pre:
        return f"{pre}{name}{suf}"
    return name


class InventoryPanel(InputBarMixin, Widget):
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
            extra = len(_BASE_ACTIONS)
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

    # ── 标签栏渲染 ──

    def _render_header(self):
        if self._tab_row == 0:
            self._render_cat_header()
        elif self._tab_row == 1:
            self._render_sort_header()
        else:
            self._render_quality_header()

    def _render_cat_header(self):
        items = self._build_cat_items()
        if not items:
            return
        if self._cat_cursor >= len(items):
            self._cat_cursor = 0

        tab_parts: list[tuple[str, int]] = []
        real_active = 0

        for i, (val, label) in enumerate(items):
            if i == self._cat_cursor:
                plain = f"\u25cf {label}"
                markup = f"[{COLOR_HINT_TAB_ACTIVE}]{plain}[/]"
                real_active = len(tab_parts)
            else:
                plain = f"  {label}"
                markup = f"  [{COLOR_HINT_TAB_DIM}]{label}[/]"
            tab_parts.append((markup, cell_len(plain)))

        update_tab_header(self, "inventory-header", tab_parts, real_active)

    def _render_sort_header(self):
        active_idx = self._sort_cursor // 2
        is_asc = (self._sort_cursor % 2 == 0)
        tab_parts: list[tuple[str, int]] = []
        real_active = 0
        for i, (val, label) in enumerate(_SORT_OPTIONS):
            if i == active_idx:
                if is_asc:
                    arrows = "\u25b2\u25bd"  # ▲▽
                else:
                    arrows = "\u25b3\u25bc"  # △▼
                plain = f"{arrows}{label}"
                markup = f"[{COLOR_HINT_TAB_ACTIVE}]{plain}[/]"
                real_active = len(tab_parts)
            else:
                plain = f"\u25b3\u25bd{label}"  # △▽
                markup = f"[{COLOR_HINT_TAB_DIM}]{plain}[/]"
            tab_parts.append((markup, cell_len(plain)))

        update_tab_header(self, "inventory-header", tab_parts, real_active)

    def _render_quality_header(self):
        items = self._build_quality_items()
        if not items:
            return
        if self._quality_cursor >= len(items):
            self._quality_cursor = 0

        tab_parts: list[tuple[str, int]] = []
        real_active = 0

        for i, (val, label) in enumerate(items):
            if i == self._quality_cursor:
                plain = f"\u25cf {label}"
                markup = f"[{COLOR_HINT_TAB_ACTIVE}]{plain}[/]"
                real_active = len(tab_parts)
            else:
                plain = f"  {label}"
                markup = f"  [{COLOR_HINT_TAB_DIM}]{label}[/]"
            tab_parts.append((markup, cell_len(plain)))

        update_tab_header(self, "inventory-header", tab_parts, real_active)

    def on_resize(self, event) -> None:
        self._render_header()

    # ── Tab 行切换 ──

    def toggle_tab_row(self):
        """Tab 键: 切换分类 / 排序 / 品质"""
        if self._mode not in (_MODE_BROWSE, _MODE_SEARCH, _MODE_MULTI_SELECT, _MODE_SELECTED):
            return
        self._tab_row = (self._tab_row + 1) % 3
        # 同步 cursor 到当前选择 (排序行无需同步, cursor 即状态)
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

    def nav_down(self):
        if self._mode in (_MODE_BROWSE, _MODE_SEARCH, _MODE_MULTI_SELECT, _MODE_SELECTED):
            if self._filtered:
                self._cursor = (self._cursor + 1) % len(self._filtered)
        elif self._mode == _MODE_ACTION:
            self._action_cursor = (self._action_cursor + 1) % len(_BASE_ACTIONS)
        elif self._mode == _MODE_USE_SUB:
            if self._use_methods:
                self._use_cursor = (self._use_cursor + 1) % len(self._use_methods)
        elif self._mode == _MODE_GIFT:
            if self._gift_friends:
                self._gift_cursor = (self._gift_cursor + 1) % len(self._gift_friends)
                self._ensure_gift_scroll()
        self._ensure_scroll()
        self._refresh_content()

    def nav_up(self):
        if self._mode in (_MODE_BROWSE, _MODE_SEARCH, _MODE_MULTI_SELECT, _MODE_SELECTED):
            if self._filtered:
                self._cursor = (self._cursor - 1) % len(self._filtered)
        elif self._mode == _MODE_ACTION:
            self._action_cursor = (self._action_cursor - 1) % len(_BASE_ACTIONS)
        elif self._mode == _MODE_USE_SUB:
            if self._use_methods:
                self._use_cursor = (self._use_cursor - 1) % len(self._use_methods)
        elif self._mode == _MODE_GIFT:
            if self._gift_friends:
                self._gift_cursor = (self._gift_cursor - 1) % len(self._gift_friends)
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
        # 搜索提交后 backspace 回到 BROWSE
        if self._mode == _MODE_SEARCH and not self._wants_insert:
            self._search_query = ""
            self._mode = _MODE_BROWSE
            self._apply_filter()
            self._scroll_offset = 0
            self._render_header()
            self._refresh_content()
            return True
        # 已选页面 backspace 回到 BROWSE
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

    # ── InputBar 标准接口 ──

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

    def _item_key(self, item: dict) -> str:
        """构造 item_id:quality 键"""
        q = item.get('quality', 0)
        return f"{item['id']}:{q}"

    def _execute_base_action(self):
        if not self._filtered or self._cursor >= len(self._filtered):
            return
        action_id, _ = _BASE_ACTIONS[self._action_cursor]
        if self._batch_mode:
            self._execute_batch_action(action_id)
            return
        item = self._filtered[self._cursor]

        if action_id == 'use':
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
            self._apply_filter()

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
            self._apply_filter()
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
            self._apply_filter()

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
            self._apply_filter()
        else:
            self._send_command(f"/gift {self._gift_item_id}")
            self._send_command(target)
            self._mode = _MODE_BROWSE
            self._apply_filter()

    def _execute_confirm(self):
        for cmd in self._confirm_cmds:
            self._send_command(cmd)
        self._confirm_cmds = []
        self._confirm_label = ''
        self._selections.clear()
        self._batch_mode = False
        self._mode = _MODE_BROWSE
        self._apply_filter()

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

    # ── 渲染 ──

    def _refresh_content(self):
        try:
            content: Static = self.query_one("#inventory-content", Static)
        except Exception:
            return

        self._update_gold_subtitle()

        if not self._filtered:
            search_hint = ""
            if self._search_query:
                search_hint = f"\n[{COLOR_FG_TERTIARY}]搜索: {self._search_query} — 无匹配[/]"
            content.update(
                f"[{COLOR_FG_TERTIARY}]暂无物品[/]{search_hint}"
            )
            return

        self._ensure_scroll()
        vh = self._visible_height()

        lines: list[str] = []

        if self._search_query:
            lines.append(f"[{COLOR_FG_TERTIARY}]搜索: {self._search_query} ({len(self._filtered)})[/]")

        if self._mode in (_MODE_MULTI_SELECT, _MODE_QUANTITY):
            n = len(self._selections)
            total = sum(self._selections.values()) if self._selections else 0
            lines.append(f"[{COLOR_FG_TERTIARY}]多选模式  已选 {n} 种 {total} 件[/]")
        elif self._mode == _MODE_SELECTED or self._batch_mode:
            n = len(self._selections)
            total = sum(self._selections.values()) if self._selections else 0
            lines.append(f"[{COLOR_FG_TERTIARY}]已选物品  {n} 种 {total} 件[/]")

        start = self._scroll_offset
        end = min(len(self._filtered), start + max(1, vh))

        for i in range(start, end):
            item = self._filtered[i]
            selected = (i == self._cursor)
            name = item.get('name', item['id'])
            quality = item.get('quality', 0)
            display_name = _quality_name(name, quality)
            count = item.get('count', 0)

            if self._mode in (_MODE_MULTI_SELECT, _MODE_QUANTITY):
                key = self._item_key(item)
                sel_qty = self._selections.get(key, 0)
                if selected:
                    marker = f"[{COLOR_ACCENT}]\u25cf[/]"
                    text = f"[bold {COLOR_FG_PRIMARY}]{display_name}[/]  [{COLOR_FG_SECONDARY}]x{count}[/]"
                elif sel_qty > 0:
                    marker = f"[{COLOR_FG_SECONDARY}]\u25cf[/]"
                    text = f"[{COLOR_FG_SECONDARY}]{display_name}[/]  [{COLOR_FG_TERTIARY}]x{count}[/]"
                else:
                    marker = f"[{COLOR_FG_TERTIARY}]\u25cb[/]"
                    text = f"[{COLOR_FG_SECONDARY}]{display_name}[/]  [{COLOR_FG_TERTIARY}]x{count}[/]"
                if sel_qty > 0:
                    text += f" [{COLOR_FG_TERTIARY}]({sel_qty})[/]"
            elif self._mode == _MODE_SELECTED or self._batch_mode:
                key = self._item_key(item)
                sel_qty = self._selections.get(key, 0)
                if selected:
                    marker = f"[{COLOR_ACCENT}]\u25cf[/]"
                    text = f"[bold {COLOR_FG_PRIMARY}]{display_name}[/]  [{COLOR_FG_SECONDARY}]x{count} \u2192 {sel_qty}[/]"
                else:
                    marker = " "
                    text = f"[{COLOR_FG_SECONDARY}]{display_name}[/]  [{COLOR_FG_TERTIARY}]x{count} \u2192 {sel_qty}[/]"
            else:
                if selected:
                    marker = f"[{COLOR_ACCENT}]\u25cf[/]"
                    text = f"[bold {COLOR_FG_PRIMARY}]{display_name}[/]  [{COLOR_FG_SECONDARY}]x{count}[/]"
                else:
                    marker = " "
                    text = f"[{COLOR_FG_SECONDARY}]{display_name}[/]  [{COLOR_FG_TERTIARY}]x{count}[/]"

            lines.append(f" {marker} {text}")

            if not selected:
                continue

            if self._mode == _MODE_ACTION:
                for ai, (_, label) in enumerate(_BASE_ACTIONS):
                    if ai == self._action_cursor:
                        lines.append(f"     [{COLOR_ACCENT}]\u25cf[/] [b]{label}[/b]")
                    else:
                        lines.append(f"       [{COLOR_FG_SECONDARY}]{label}[/]")

            elif self._mode == _MODE_USE_SUB:
                if not self._use_methods:
                    lines.append(f"     [{COLOR_FG_TERTIARY}]此物品无法使用[/]")
                else:
                    for ui, method in enumerate(self._use_methods):
                        if ui == self._use_cursor:
                            lines.append(f"       [{COLOR_ACCENT}]\u25cf[/] [b]{method['name']}[/b]")
                        else:
                            lines.append(f"         [{COLOR_FG_SECONDARY}]{method['name']}[/]")

            elif self._mode == _MODE_INPUT:
                lines.append(f"     [{COLOR_FG_SECONDARY}]{self._input_label}[/]")

            elif self._mode == _MODE_GIFT:
                lines += self._render_gift_lines()

            elif self._mode == _MODE_QUANTITY:
                lines.append(f"     [{COLOR_FG_SECONDARY}]{self._input_label}[/]")

            elif self._mode == _MODE_CONFIRM:
                lines.append(f"     [{COLOR_FG_SECONDARY}]{self._confirm_label}[/]")

            elif self._mode == _MODE_DETAIL:
                desc = item.get('desc') or '暂无描述'
                cat_label = _FILTER_LABELS.get(item.get('category', ''), item.get('category', ''))
                qual_label = _QUALITY_LABELS.get(str(quality), '普通')
                lines.append(f"     [{COLOR_FG_SECONDARY}]{desc}[/]")
                detail_parts = []
                if cat_label:
                    detail_parts.append(f"分类: {cat_label}")
                detail_parts.append(f"品质: {qual_label}")
                lines.append(f"     [{COLOR_FG_TERTIARY}]{'  '.join(detail_parts)}[/]")

        # 滚动指示
        total = len(self._filtered)
        if total > end - start:
            lines.append(f"[{COLOR_FG_TERTIARY}]  {self._cursor + 1}/{total}[/]")

        content.update("\n".join(lines))

    def _render_gift_lines(self) -> list[str]:
        lines = []
        if not self._gift_friends:
            hint = "搜索好友..." if not self._gift_query else "无匹配好友"
            lines.append(f"     [{COLOR_FG_TERTIARY}]{hint}[/]")
            return lines

        total = len(self._gift_friends)
        offset = max(0, min(self._gift_scroll, total - _MAX_GIFT_VISIBLE))
        self._gift_scroll = offset
        vis_end = min(total, offset + _MAX_GIFT_VISIBLE)

        for gi in range(offset, vis_end):
            fname = self._gift_friends[gi]
            if gi == self._gift_cursor:
                lines.append(f"     [{COLOR_ACCENT}]\u25cf[/] [bold {COLOR_FG_PRIMARY}]{fname}[/]")
            else:
                lines.append(f"       [{COLOR_FG_SECONDARY}]{fname}[/]")

        if total > _MAX_GIFT_VISIBLE:
            lines.append(f"     [{COLOR_FG_TERTIARY}]{self._gift_cursor + 1}/{total}[/]")

        return lines

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event == 'update_inventory':
            self._sync_from_state()

    def _sync_from_state(self):
        st = self._state
        self._items = list(st.items)
        self._gold = st.gold
        self._filter_tab = st.filter_tab
        self._quality_filter = st.quality_filter
        self._sort_cursor = st.sort_cursor
        self._tab_row = st.tab_row
        self._cursor = st.cursor
        # 从 filter 值推导出对应的 header cursor 位置
        cat_items = self._build_cat_items()
        self._cat_cursor = next(
            (i for i, (v, _) in enumerate(cat_items) if v == self._filter_tab), 0)
        qual_items = self._build_quality_items()
        self._quality_cursor = next(
            (i for i, (v, _) in enumerate(qual_items) if v == self._quality_filter), 0)
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
        self._state.set_listener(self._on_state_event)
        self._sync_from_state()

    def on_unmount(self):
        if self._state_mgr:
            st = self._state_mgr.inventory
            st.cursor = self._cursor
            st.filter_tab = self._filter_tab
            st.quality_filter = self._quality_filter
            st.sort_cursor = self._sort_cursor
            st.tab_row = self._tab_row

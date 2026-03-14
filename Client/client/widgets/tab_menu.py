"""TabMenuBase — 标签页+列表菜单基类"""

from textual.widgets import Static
from textual.containers import Vertical
from rich.table import Table

from ..config import COLOR_HINT_TAB_ACTIVE, COLOR_HINT_TAB_DIM

MAX_TAB_VISIBLE = 4


def _text_width(s: str) -> int:
    """纯文本显示宽度 — 使用 Rich 的 cell_len 保证与渲染一致"""
    from rich.cells import cell_len
    return cell_len(s)


class TabMenuBase(Vertical):
    """标签页菜单通用基类 — CommandHintBar 和 WhichKeyPanel 共同继承。

    子类需重写：
      _item_name(item) -> str    — 项目显示名
      _item_desc(item) -> str    — 项目描述
      _item_sub(item) -> list|None — 子菜单列表
      _make_sub_tab(item) -> tuple — 进入子菜单时的 (tab_name, sub_items) 元组
    """

    _tabs_widget_id: str = ""
    _content_widget_id: str = ""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._tabs: list[tuple[str, list]] = []
        self._active_tab: int = 0
        self._selected_idx: int = 0
        self._scroll_offset: int = 0
        self._nav_stack: list[dict] = []

    # ── 子类钩子（必须重写）──

    def _item_name(self, item) -> str:
        raise NotImplementedError

    def _item_desc(self, item) -> str:
        raise NotImplementedError

    def _item_sub(self, item) -> list | None:
        raise NotImplementedError

    def _make_sub_tab(self, item) -> tuple[str, list]:
        raise NotImplementedError

    # ── 数据 ──

    def update_tabs(self, tabs: list[tuple[str, list]]):
        self._tabs = tabs
        if self._active_tab >= len(tabs):
            self._active_tab = 0
        self._selected_idx = 0
        self._scroll_offset = 0
        self._nav_stack = []
        self._refresh_display()

    def _current_items(self) -> list:
        if self._tabs and self._active_tab < len(self._tabs):
            return self._tabs[self._active_tab][1]
        return []

    # ── 导航 ──

    def nav_left(self):
        if not self._tabs or self._nav_stack:
            return
        self._active_tab = (self._active_tab - 1) % len(self._tabs)
        self._selected_idx = 0
        self._scroll_offset = 0
        self._refresh_display()

    def nav_right(self):
        if not self._tabs or self._nav_stack:
            return
        self._active_tab = (self._active_tab + 1) % len(self._tabs)
        self._selected_idx = 0
        self._scroll_offset = 0
        self._refresh_display()

    def nav_down(self):
        items = self._current_items()
        if not items:
            return
        self._selected_idx = (self._selected_idx + 1) % len(items)
        self._ensure_scroll()
        self._refresh_display()

    def nav_up(self):
        items = self._current_items()
        if not items:
            return
        self._selected_idx = (self._selected_idx - 1) % len(items)
        self._ensure_scroll()
        self._refresh_display()

    def enter(self):
        """Enter: 若选中项有子菜单则钻入（返回 None），否则返回该项"""
        items = self._current_items()
        if not items or self._selected_idx >= len(items):
            return None
        item = items[self._selected_idx]
        sub = self._item_sub(item)
        if sub is not None:
            self._push_stack()
            tab_name, sub_items = self._make_sub_tab(item)
            self._tabs = [(tab_name, sub_items)]
            self._active_tab = 0
            self._selected_idx = 0
            self._scroll_offset = 0
            self._refresh_display()
            return None
        return item

    def back(self) -> bool:
        """Backspace: 从子菜单返回上级。返回 True=成功退回，False=已在顶级。"""
        if self._nav_stack:
            state = self._nav_stack.pop()
            self._tabs = state['tabs']
            self._active_tab = state['active_tab']
            self._selected_idx = state['selected_idx']
            self._scroll_offset = state['scroll_offset']
            self._on_restore_stack(state)
            self._refresh_display()
            return True
        return False

    def reset_to_root(self):
        """重置到根菜单（逐层弹出导航栈恢复根状态）"""
        while self._nav_stack:
            state = self._nav_stack.pop()
            self._tabs = state['tabs']
            self._active_tab = state['active_tab']
            self._on_restore_stack(state)
        self._selected_idx = 0
        self._scroll_offset = 0
        self._refresh_display()

    # ── 内部 ──

    def _push_stack(self):
        """保存当前状态到导航栈"""
        self._nav_stack.append({
            'tabs': self._tabs,
            'active_tab': self._active_tab,
            'selected_idx': self._selected_idx,
            'scroll_offset': self._scroll_offset,
        })

    def _on_restore_stack(self, state: dict):
        """子类可重写以恢复额外状态"""
        pass

    def _ensure_scroll(self):
        if self._selected_idx < self._scroll_offset:
            self._scroll_offset = self._selected_idx
        elif self._selected_idx >= self._scroll_offset + MAX_TAB_VISIBLE:
            self._scroll_offset = self._selected_idx - MAX_TAB_VISIBLE + 1

    def _refresh_display(self):
        if not self._tabs:
            self._update_widgets("", "")
            return
        tab_text = self._render_tabs()
        content = self._render_items()
        self._update_widgets(tab_text, content)

    def on_resize(self, event) -> None:
        """窗口尺寸变化时重新渲染标签页（防止截断）"""
        if self._tabs:
            self._refresh_display()

    def _update_widgets(self, tab_text, content):
        try:
            self.query_one(f"#{self._tabs_widget_id}", Static).update(tab_text)
            self.query_one(f"#{self._content_widget_id}", Static).update(content)
        except Exception:
            pass

    def _render_tabs(self) -> str:
        if self._nav_stack:
            return f"  [{COLOR_HINT_TAB_ACTIVE}]<[/] [bold {COLOR_HINT_TAB_ACTIVE}]{self._tabs[0][0]}[/]"

        # 计算每个标签页的显示文本及纯文本宽度
        tab_parts = []
        for i, (name, _) in enumerate(self._tabs):
            if i == self._active_tab:
                plain = f"● {name}"
                tab_parts.append((f"[bold {COLOR_HINT_TAB_ACTIVE}]{plain}[/]", _text_width(plain)))
            else:
                plain = f"  {name}"
                tab_parts.append((f"[{COLOR_HINT_TAB_DIM}]{plain}[/]", _text_width(plain)))

        total_width = sum(w for _, w in tab_parts)

        # 获取容器可用宽度（若无法获取则用较大默认值）
        try:
            avail = self.query_one(f"#{self._tabs_widget_id}").size.width
        except Exception:
            avail = 120
        if avail <= 0:
            avail = 120

        # 全部放得下 → 直接拼接
        if total_width <= avail:
            return "".join(p for p, _ in tab_parts)

        # 需要滚动 — 以 active_tab 为中心，向左右扩展
        arrow_w = 2  # "‹ " 或 " ›"
        budget = avail
        selected = [(self._active_tab, tab_parts[self._active_tab])]
        used = tab_parts[self._active_tab][1]
        lo = self._active_tab - 1
        hi = self._active_tab + 1
        need_left = lo >= 0
        need_right = hi < len(tab_parts)

        while True:
            grew = False
            if lo >= 0:
                cost = tab_parts[lo][1] + (arrow_w if lo > 0 else 0)
                if used + cost + (arrow_w if need_right else 0) <= budget:
                    selected.insert(0, (lo, tab_parts[lo]))
                    used += tab_parts[lo][1]
                    lo -= 1
                    need_left = lo >= 0
                    grew = True
            if hi < len(tab_parts):
                cost = tab_parts[hi][1] + (arrow_w if hi < len(tab_parts) - 1 else 0)
                if used + cost + (arrow_w if need_left else 0) <= budget:
                    selected.append((hi, tab_parts[hi]))
                    used += tab_parts[hi][1]
                    hi += 1
                    need_right = hi < len(tab_parts)
                    grew = True
            if not grew:
                break

        need_left = lo >= 0
        need_right = hi < len(tab_parts)
        result = ""
        if need_left:
            result += f"[{COLOR_HINT_TAB_DIM}]< [/]"
        result += "".join(p for _, (p, _) in selected)
        if need_right:
            result += f"[{COLOR_HINT_TAB_DIM}] >[/]"
        return result

    def _render_items(self):
        items = self._current_items()
        total = len(items)
        offset = self._scroll_offset

        if total > MAX_TAB_VISIBLE:
            offset = max(0, min(offset, total - MAX_TAB_VISIBLE))
            self._scroll_offset = offset

        visible = items[offset:offset + MAX_TAB_VISIBLE]

        if not visible:
            return f"[{COLOR_HINT_TAB_DIM}]  暂无可用项目[/]"

        need_sb = total > MAX_TAB_VISIBLE

        table = Table(
            show_header=False, show_edge=False,
            box=None, expand=True, padding=(0, 0), pad_edge=False,
        )
        table.add_column(width=2, no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column(justify="right", style=COLOR_HINT_TAB_DIM, ratio=1, no_wrap=True)
        if need_sb:
            table.add_column(width=1, no_wrap=True)
            max_off = max(1, total - MAX_TAB_VISIBLE)
            thumb_size = max(1, round(MAX_TAB_VISIBLE / total * MAX_TAB_VISIBLE))
            track_space = MAX_TAB_VISIBLE - thumb_size
            thumb_start = round(offset / max_off * track_space) if track_space > 0 else 0

        for i, item in enumerate(visible):
            real_idx = offset + i
            if real_idx == self._selected_idx:
                arrow = f"[bold {COLOR_HINT_TAB_ACTIVE}]● [/]"
            else:
                arrow = "  "
            row = [arrow, self._item_name(item), self._item_desc(item)]
            if need_sb:
                if thumb_start <= i < thumb_start + thumb_size:
                    row.append(f"[{COLOR_HINT_TAB_ACTIVE}]█[/]")
                else:
                    row.append(f"[{COLOR_HINT_TAB_DIM}]│[/]")
            table.add_row(*row)

        for _ in range(MAX_TAB_VISIBLE - len(visible)):
            row = ["", "", ""]
            if need_sb:
                row.append("")
            table.add_row(*row)

        return table

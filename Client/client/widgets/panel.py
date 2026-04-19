"""Panel — 通用 TUI 面板基类

框架层：边框 + tab 栏 + 可选 input row。
正文区由子类覆写 compose_content() 提供。
"""

from __future__ import annotations
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, Input
from textual.containers import Horizontal, VerticalScroll
from textual.app import ComposeResult
from ..config import (
    COLOR_BORDER, COLOR_FG_SECONDARY, COLOR_FG_PRIMARY,
    COLOR_FG_TERTIARY, COLOR_HINT_TAB_DIM,
    ICON_INDENT,
)


class PlayerSelected(Message):
    """用户选中某个玩家"""
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


def text_width(s: str) -> int:
    """纯文本显示宽度 — 使用 Rich 的 cell_len 保证与渲染一致"""
    from rich.cells import cell_len
    return cell_len(s)


class Panel(Widget):

    DEFAULT_CSS = f"""
    Panel {{
        border: round {COLOR_BORDER};
        border-title-color: {COLOR_FG_SECONDARY};
        border-subtitle-color: {COLOR_FG_SECONDARY};
        background: transparent;
        padding: 0;
    }}
    Panel > #input-row {{
        dock: top; height: 2;
        border-bottom: solid {COLOR_BORDER}; padding: 0; background: transparent;
    }}
    Panel > #input-row > #prompt {{ width: 2; height: 1; color: {COLOR_FG_TERTIARY}; padding: 0; }}
    Panel > #input-row > #input  {{ width: 1fr; height: 1; border: none; padding: 0; color: {COLOR_FG_PRIMARY}; background: transparent; }}
    Panel > #input-row > #input:focus {{ border: none; background: transparent; }}
    Panel > #input-row > #input:disabled {{ background: transparent; color: {COLOR_FG_TERTIARY}; }}
    Panel > .tab {{
        height: 1fr;
        scrollbar-size-vertical: 1;
        scrollbar-background: transparent;
        scrollbar-background-hover: transparent;
        scrollbar-background-active: transparent;
        scrollbar-color: {COLOR_FG_SECONDARY};
        scrollbar-color-hover: {COLOR_FG_PRIMARY};
        scrollbar-color-active: {COLOR_FG_PRIMARY};
    }}
    Panel > .tab > .content {{ padding: 0 1 0 2; }}
    Panel > .tab > .content.icon-align {{ padding: 0 0 0 0; }}
    Panel > .tab > .content.full-width {{ padding: 0; }}
    """

    tabs: list[str] = []
    has_input: bool = False
    icon_align: bool = False
    full_width_content: bool = False
    hide_scrollbar: bool = False
    follow_focus: bool = False
    title: str = ""
    subtitle: str = ""
    placeholder: str = "输入..."

    def __init__(self, **kw):
        for attr in ("tabs", "has_input", "title", "subtitle", "placeholder"):
            if attr in kw:
                setattr(self, attr, kw.pop(attr))
        super().__init__(**kw)
        self._active = 0
        self._cursor: int = 0
        self._confirm_cursor: int = 0
        self._unread: set[int] = set()

    def compose(self) -> ComposeResult:
        if self.has_input:
            with Horizontal(id="input-row"):
                yield Static("❯ ", id="prompt")
                yield Input(placeholder=self.placeholder, id="input", disabled=True)
        yield from self.compose_content()

    def compose_content(self) -> ComposeResult:
        """子类覆写此方法提供正文区 widget。默认实现：按 tabs 数量生成 VerticalScroll+Static。"""
        for i in range(max(len(self.tabs), 1)):
            with VerticalScroll(classes="tab", id=f"t{i}"):
                yield Static("", classes="content", markup=True)

    def on_mount(self) -> None:
        self.border_title = self._render_tabs() or self.title
        self.border_subtitle = self.subtitle
        for inp in self.query(Input):
            inp.select_on_focus = False
        for i, t in enumerate(self.query(".tab")):
            t.display = i == self._active
        if self.icon_align:
            for c in self.query(".content"):
                c.add_class("icon-align")
        if self.full_width_content:
            for c in self.query(".content"):
                c.add_class("full-width")
        if self.hide_scrollbar:
            for t in self.query(".tab"):
                t.styles.scrollbar_size_vertical = 0
                t.styles.scrollbar_size_horizontal = 0

    # ── 标签 ──

    def _render_tabs(self) -> str:
        if not self.tabs:
            return ""
        parts = []
        for i, n in enumerate(self.tabs):
            mark = "*" if i in self._unread else ""
            color = f"bold {COLOR_FG_PRIMARY}" if i == self._active else COLOR_HINT_TAB_DIM
            parts.append(f"[{color}]{n}{mark}[/]")
        return " ".join(parts)

    def switch_tab(self, index: int) -> None:
        if not self.tabs:
            return
        index %= len(self.tabs)
        if index == self._active:
            return
        self.query_one(f"#t{self._active}").display = False
        self._active = index
        self._unread.discard(index)
        self.query_one(f"#t{index}").display = True
        self.border_title = self._render_tabs()

    def mark_unread(self, tab: int) -> None:
        if tab != self._active:
            self._unread.add(tab)
            self.border_title = self._render_tabs()

    # ── 内容（默认 VerticalScroll+Static 实现用）──

    def _content_width(self, tab: int | None = None) -> int:
        """获取当前 tab 正文区可用文本宽度"""
        tab = self._active if tab is None else tab
        try:
            content = self.query_one(f"#t{tab} .content", Static)
            w = content.content_region.width
            if w > 0:
                return w
        except Exception:
            pass
        # layout 未完成时用面板外框宽度估算
        pw = self.content_region.width
        return max(pw - 2, 1) if pw > 0 else 1

    def _separator_line(self, style: str = '') -> str:
        """生成全宽分割线 markup"""
        w = self._content_width()
        line = '─' * w
        return f'[{style}]{line}[/]' if style else line

    def update(self, text: str, tab: int | None = None, focus_line: int = -1) -> None:
        tab = self._active if tab is None else tab
        self.query_one(f"#t{tab} .content", Static).update(text)
        if focus_line >= 0:
            self.scroll_to_line(focus_line, tab)
        elif self.follow_focus and hasattr(self, '_focus_line') and self._focus_line >= 0:
            self.scroll_to_line(self._focus_line, tab)

    def append(self, text: str, tab: int | None = None) -> None:
        tab = self._active if tab is None else tab
        vs = self.query_one(f"#t{tab}", VerticalScroll)
        at_bottom = vs.scroll_offset.y >= vs.max_scroll_y - 1
        content = self.query_one(f"#t{tab} .content", Static)
        old = content.content
        content.update(f"{old}\n{text}" if old else text)
        if at_bottom:
            vs.scroll_end(animate=False)

    def get_input_widget(self) -> Input | None:
        return self.query_one("#input", Input) if self.has_input else None

    def scroll_to_line(self, line: int, tab: int | None = None, margin: int = 3) -> None:
        """滚动使指定行可见（0-indexed），下方保留 margin 行裕度"""
        tab = self._active if tab is None else tab
        vs = self.query_one(f"#t{tab}", VerticalScroll)
        top = vs.scroll_offset.y
        height = vs.size.height
        if line < top:
            vs.scroll_to(y=line, animate=False)
        elif line + margin >= top + height:
            vs.scroll_to(y=line + margin - height + 1, animate=False)

    # ── 光标列表 ──

    def _move_cursor(self, delta: int, total: int) -> bool:
        """移动光标，clamp 到 [0, total-1]。返回是否实际移动。"""
        if total <= 0:
            return False
        new = max(0, min(total - 1, self._cursor + delta))
        if new == self._cursor:
            return False
        self._cursor = new
        return True

    def _render_cursor_items(
        self,
        items: list[str],
        formatter=None,
    ) -> str:
        """渲染光标列表。

        items: 显示标签列表。
        formatter: 可选 (index, label, selected) -> str 覆盖默认格式。
        返回 '\\n'.join 的 markup 字符串。
        """
        lines: list[str] = []
        for i, label in enumerate(items):
            selected = i == self._cursor
            if formatter:
                lines.append(formatter(i, label, selected))
            elif selected:
                lines.append(f"[bold {COLOR_FG_PRIMARY}]> {label}[/]")
            else:
                lines.append(f"[{COLOR_FG_TERTIARY}]{ICON_INDENT}{label}[/]")
        return '\n'.join(lines)

    def _cursor_nav(self, action: str, total: int, on_enter=None, redraw=None) -> bool:
        """通用光标导航。处理 up/down/enter，返回 True 表示已处理。

        on_enter: 可选回调，enter 时调用。
        redraw: 可选回调，光标移动后调用（默认无）。
        """
        match action:
            case 'up':
                if self._move_cursor(-1, total):
                    if redraw:
                        redraw()
                return True
            case 'down':
                if self._move_cursor(1, total):
                    if redraw:
                        redraw()
                return True
            case 'enter':
                if on_enter:
                    on_enter()
                return True
        return False

    # ── 确认对话框 ──

    def _render_confirm(self, msg: str, color: str = COLOR_FG_TERTIARY) -> str:
        """渲染「是/否」确认对话框，返回 markup 字符串。"""
        lines = [
            f"[{color}]{ICON_INDENT}{msg}[/]",
            self._separator_line(color),
        ]
        for i, label in enumerate(('是', '否')):
            if i == self._confirm_cursor:
                lines.append(f"[bold {COLOR_FG_PRIMARY}]> {label}[/]")
            else:
                lines.append(f"[{color}]{ICON_INDENT}{label}[/]")
        return '\n'.join(lines)

    def _nav_confirm(self, action: str, on_yes, on_dismiss=None) -> bool:
        """处理确认对话框导航。返回 True 表示已消费事件。

        on_yes: Enter+是 时调用。
        on_dismiss: Enter+否 或 Escape 时调用。默认只重置 _confirm_cursor。
        """
        if action == 'up':
            if self._confirm_cursor > 0:
                self._confirm_cursor = 0
            return True
        if action == 'down':
            if self._confirm_cursor < 1:
                self._confirm_cursor = 1
            return True
        if action == 'enter':
            if self._confirm_cursor == 0:
                on_yes()
            elif on_dismiss:
                on_dismiss()
            self._confirm_cursor = 0
            return True
        if action == 'escape':
            if on_dismiss:
                on_dismiss()
            self._confirm_cursor = 0
            return True
        return False

    # ── 导航 ──

    def reset_cursor(self) -> None:
        """重置光标（窗口重新打开时调用）。子类可 super() 后追加逻辑。"""
        self._cursor = 0
        self._confirm_cursor = 0

    def nav(self, action: str) -> None:
        match action:
            case "up":       self.query_one(f"#t{self._active}", VerticalScroll).scroll_up(animate=False)
            case "down":     self.query_one(f"#t{self._active}", VerticalScroll).scroll_down(animate=False)
            case "tab_prev": self.switch_tab(self._active - 1)
            case "tab_next": self.switch_tab(self._active + 1)


# ── 工具函数 ──

_AVAIL_FALLBACK = 1


def _widget_width(widget, widget_id: str = "") -> int:
    """获取 widget 内容可用宽度，获取不到时返回 fallback。"""
    if widget_id:
        w = widget.query_one(f"#{widget_id}")
        scr = w.scrollable_content_region.width
        if scr > 0:
            return scr
    scr = widget.scrollable_content_region.width
    if scr > 0:
        return scr
    return _AVAIL_FALLBACK


def _widget_height(widget, widget_id: str = "") -> int:
    """获取 widget 内容可用高度，获取不到时返回 fallback。"""
    if widget_id:
        w = widget.query_one(f"#{widget_id}")
        scr = w.scrollable_content_region.height
        if scr > 0:
            return scr
    scr = widget.scrollable_content_region.height
    if scr > 0:
        return scr
    return _AVAIL_FALLBACK

"""Panel — 通用 TUI 面板组件"""

from __future__ import annotations
from textual.widget import Widget
from textual.widgets import Static, Input
from textual.containers import Horizontal, VerticalScroll
from textual.app import ComposeResult
from .config import BORDER, BORDER_TITLE, FG, FG_DIM, TAB_DIM, SCROLLBAR, SCROLLBAR_HOVER


class Panel(Widget):

    DEFAULT_CSS = f"""
    Panel {{
        border: round {BORDER};
        border-title-color: {BORDER_TITLE};
        border-subtitle-color: {BORDER_TITLE};
        background: transparent;
        padding: 0;
    }}
    Panel > #input-row {{
        dock: top; height: 2;
        border-bottom: solid {BORDER}; padding: 0;
    }}
    Panel > #input-row > #prompt {{ width: 2; height: 1; color: {FG_DIM}; padding: 0; }}
    Panel > #input-row > #input  {{ width: 1fr; height: 1; border: none; padding: 0; color: {FG}; }}
    Panel > #input-row > #input:focus {{ border: none; }}
    Panel > .tab {{
        height: 1fr;
        scrollbar-size-vertical: 1;
        scrollbar-background: transparent;
        scrollbar-background-hover: transparent;
        scrollbar-background-active: transparent;
        scrollbar-color: {SCROLLBAR};
        scrollbar-color-hover: {SCROLLBAR_HOVER};
        scrollbar-color-active: {SCROLLBAR_HOVER};
    }}
    Panel > .tab > .content {{ padding: 0 0 0 2; }}
    """

    tabs: list[str] = []
    has_input: bool = False
    title: str = ""
    subtitle: str = ""
    placeholder: str = "输入..."

    def __init__(self, **kw):
        for attr in ("tabs", "has_input", "title", "subtitle", "placeholder"):
            if attr in kw:
                setattr(self, attr, kw.pop(attr))
        super().__init__(**kw)
        self._active = 0
        self._unread: set[int] = set()

    def compose(self) -> ComposeResult:
        if self.has_input:
            with Horizontal(id="input-row"):
                yield Static("❯ ", id="prompt")
                yield Input(placeholder=self.placeholder, id="input", disabled=True)
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

    # ── 标签 ──

    def _render_tabs(self) -> str:
        if not self.tabs:
            return ""
        parts = []
        for i, n in enumerate(self.tabs):
            mark = "*" if i in self._unread else ""
            color = f"bold {FG}" if i == self._active else TAB_DIM
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

    # ── 内容 ──

    def update(self, text: str, tab: int | None = None) -> None:
        tab = self._active if tab is None else tab
        self.query_one(f"#t{tab} .content", Static).update(text)

    def append(self, text: str, tab: int | None = None) -> None:
        tab = self._active if tab is None else tab
        vs = self.query_one(f"#t{tab}", VerticalScroll)
        at_bottom = vs.scroll_offset.y >= vs.max_scroll_y - 1
        content = self.query_one(f"#t{tab} .content", Static)
        old = content.renderable
        content.update(f"{old}\n{text}" if old else text)
        if at_bottom:
            vs.scroll_end(animate=False)

    def get_input_widget(self) -> Input | None:
        return self.query_one("#input", Input) if self.has_input else None

    # ── 导航 ──

    def nav(self, action: str) -> None:
        match action:
            case "up":       self.query_one(f"#t{self._active}", VerticalScroll).scroll_up(animate=False)
            case "down":     self.query_one(f"#t{self._active}", VerticalScroll).scroll_down(animate=False)
            case "tab_prev": self.switch_tab(self._active - 1)
            case "tab_next": self.switch_tab(self._active + 1)

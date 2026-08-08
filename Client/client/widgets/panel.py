"""Panel — 通用 TUI 面板基类

框架层：边框 + tab 栏 + 可选 input row。
正文区由子类覆写 compose_content() 提供。
"""

from __future__ import annotations
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, Input
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.app import ComposeResult
from ..config import (
    COLOR_BORDER, COLOR_FG_SECONDARY, COLOR_FG_PRIMARY,
    COLOR_FG_TERTIARY, COLOR_HINT_TAB_DIM,
    ICON_INDENT,
)
from ..window_engine import (
    ConfirmMenu,
    Divider,
    EngineInput,
    InputSession,
    InputSpec,
    Option,
    ScrollPolicy,
    SelectList,
    SurfaceState,
)
from ..window_engine.text import cell_width

PanelSeparator = Divider


class PlayerSelected(Message):
    """用户选中某个玩家"""
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


def text_width(s: str) -> int:
    """兼容旧调用；新代码使用 window_engine.text.cell_width。"""
    return cell_width(s)


class Panel(Widget):

    DEFAULT_CSS = f"""
    Panel {{
        border: round {COLOR_BORDER};
        border-title-color: {COLOR_FG_SECONDARY};
        border-subtitle-color: {COLOR_FG_SECONDARY};
        background: transparent;
        padding: 0;
    }}
    Panel > #input-region {{
        dock: top;
        width: 1fr;
        height: 2;
    }}
    Panel > #input-region > #input-row {{
        height: 1;
        padding: 0; background: transparent;
    }}
    Panel > #input-region > #input-divider {{
        height: 1;
    }}
    Panel > #input-region > #input-row > #prompt {{ width: 2; height: 1; color: {COLOR_FG_TERTIARY}; padding: 0; }}
    Panel > #input-region > #input-row > #input  {{ width: 1fr; height: 1; border: none; padding: 0; color: {COLOR_FG_PRIMARY}; background: transparent; }}
    Panel > #input-region > #input-row > #input:focus {{ border: none; background: transparent; }}
    Panel > #input-region > #input-row > #input:disabled {{ background: transparent; color: {COLOR_FG_TERTIARY}; }}
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
    Panel > #panel-confirm-surface {{
        display: none;
        height: auto;
    }}
    Panel #panel-confirm-divider {{ height: 1; }}
    Panel #panel-confirm-options {{
        height: auto;
        padding: 0 1 0 2;
    }}
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
        self.selection = SelectList()
        self.confirmation = ConfirmMenu()
        self.surface_state = SurfaceState()
        self.input_session = InputSession(
            InputSpec(
                context_id="default",
                placeholder=self.placeholder,
                visible=self.has_input,
                enabled=self.has_input,
                focus=True,
            )
        )
        self._unread: set[int] = set()

    def compose(self) -> ComposeResult:
        if self.has_input:
            with Vertical(id="input-region"):
                with Horizontal(id="input-row"):
                    yield Static("> ", id="prompt")
                    yield EngineInput(
                        placeholder=self.placeholder, id="input", disabled=True,
                    )
                yield Divider(style=COLOR_BORDER, id="input-divider")
        yield from self.compose_content()
        with Vertical(id="panel-confirm-surface"):
            yield Divider(
                style=COLOR_BORDER, id="panel-confirm-divider",
            )
            yield Static(
                "", id="panel-confirm-options", markup=True,
            )

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
        if self.has_input:
            self.input_session.mount(
                self.query_one("#input", Input),
                self.query_one("#input-row"),
                self.query_one("#input-divider", Divider),
                self.query_one("#input-region"),
            )
            self.activate_input_context()
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
            self._hide_confirm_surface()

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
        self.activate_input_context()

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
            scroll = self.query_one(f"#t{tab}", VerticalScroll)
            w = ScrollPolicy.content_width(content, scroll)
            if w > 0:
                return w
        except Exception:
            pass
        # layout 未完成时用面板外框宽度估算
        pw = self.content_region.width
        return max(pw - 2, 1) if pw > 0 else 1

    def set_scrollbar_visible(
        self, visible: bool, tab: int | None = None,
    ) -> None:
        """Apply the shared scrollbar reservation to one or every tab."""
        tabs = self.query(".tab") if tab is None else [
            self.query_one(f"#t{tab}", VerticalScroll),
        ]
        for scroll in tabs:
            ScrollPolicy.set_vertical_visible(scroll, visible)

    def update(self, text: str, tab: int | None = None, focus_line: int = -1) -> None:
        tab = self._active if tab is None else tab
        scroll = self.query_one(f"#t{tab}", VerticalScroll)
        content = self.query_one(f"#t{tab} .content", Static)
        target_line = focus_line
        if (
                target_line < 0
                and self.follow_focus
                and hasattr(self, '_focus_line')):
            target_line = self._focus_line
        if target_line >= 0:
            content.update(text)
            self.scroll_to_line(target_line, tab)
            self.call_after_refresh(self.scroll_to_line, target_line, tab)
            return
        ScrollPolicy.update(
            scroll,
            lambda: content.update(text),
            self.call_after_refresh,
            self.reflow_content,
        )

    def append(self, text: str, tab: int | None = None) -> None:
        tab = self._active if tab is None else tab
        vs = self.query_one(f"#t{tab}", VerticalScroll)
        content = self.query_one(f"#t{tab} .content", Static)
        old = content.content
        ScrollPolicy.update(
            vs,
            lambda: content.update(f"{old}\n{text}" if old else text),
            self.call_after_refresh,
            self.reflow_content,
        )

    def replace_last(self, text: str, tab: int | None = None) -> None:
        """替换最后一行内容"""
        tab = self._active if tab is None else tab
        content = self.query_one(f"#t{tab} .content", Static)
        old = str(content.content)
        idx = old.rfind('\n')
        content.update(f"{old[:idx]}\n{text}" if idx >= 0 else text)

    def get_input_widget(self) -> Input | None:
        return self.query_one("#input", Input) if self.has_input else None

    def configure_input(self, **changes) -> None:
        """Declare the current tab's input intent without manipulating widgets."""
        self.input_session.configure(**changes)

    def replace_input_spec(self, spec: InputSpec) -> None:
        self.input_session.replace(spec)

    def input_spec(self) -> InputSpec:
        """Declare input behavior for the active tab or panel context."""
        return InputSpec(
            context_id=f"{self.id or type(self).__name__}:{self._active}",
            placeholder=self.placeholder,
            visible=self.has_input,
            enabled=self.has_input,
            focus=True,
        )

    def activate_input_context(self) -> None:
        """Synchronize input intent after tab/window/context changes."""
        if self.has_input:
            self.input_session.replace(self.input_spec())

    def set_options(self, options, context_id: str) -> None:
        """Replace the focused list through its shared selection state."""
        self.surface_state = SurfaceState()
        self.selection.set_options(options, context_id)

    @property
    def selected_option(self) -> Option | None:
        """The selected option in this panel's current interaction context."""
        return self.selection.selected

    def render_options(self, *, width: int | None = None, **styles: str) -> str:
        """Render the panel selection with the common cursor and text wrapping."""
        return self.selection.render(
            self._content_width() if width is None else width,
            idle_prefix=ICON_INDENT,
            selected_style=f"bold {COLOR_FG_PRIMARY}",
            idle_style=COLOR_FG_TERTIARY,
            **styles,
        )

    def selected_line(self, *, width: int | None = None) -> int:
        """Return the selected option's rendered line after cell wrapping."""
        return self.selection.selected_line(
            self._content_width() if width is None else width,
            idle_prefix=ICON_INDENT,
        )

    def _render_confirm(
        self, message: str, color: str = COLOR_FG_TERTIARY,
    ) -> str:
        if not self.confirmation.is_open:
            self.confirmation.open(
                message, context_id=f"panel-confirmation:{message}",
            )
        self.confirmation.message = message
        self.query_one("#panel-confirm-surface", Vertical).display = True
        options = self.query_one("#panel-confirm-options", Static)
        options.update(self.confirmation.selection.render(
            self._content_width(),
            idle_prefix=ICON_INDENT,
            selected_style=f"bold {COLOR_FG_PRIMARY}",
            idle_style=color,
        ))
        return message

    def _hide_confirm_surface(self) -> None:
        self.query_one("#panel-confirm-surface", Vertical).display = False

    def _nav_confirm(self, action: str, on_yes, on_dismiss=None) -> bool:
        if not self.confirmation.is_open:
            self.confirmation.open("", context_id="panel-confirmation")
        if action not in ("up", "down", "enter"):
            return False
        result = self.confirmation.handle(action)
        if result == ConfirmMenu.YES_ID:
            self._hide_confirm_surface()
            on_yes()
        elif result == ConfirmMenu.NO_ID and on_dismiss:
            self._hide_confirm_surface()
            on_dismiss()
        return True

    def enter_insert(self, *, sticky: bool = False) -> bool:
        """Activate this panel's declared input session."""
        can_enter = getattr(self, "can_enter_insert", None)
        if can_enter is not None and not can_enter():
            return False
        prepare = getattr(self, "prepare_insert", None)
        if prepare is not None:
            prepare()
        return self.input_session.enter(sticky=sticky)

    def leave_insert(self, *, preserve: bool = True) -> None:
        """Leave INSERT while preserving drafts unless explicitly discarded."""
        self.input_session.leave(preserve=preserve)

    def submit_input(self, event: Input.Submitted, *, clear: bool = False) -> str:
        """Read through the shared session so views never mutate ``Input``."""
        return self.input_session.submit(event.value, clear=clear)

    def sync_primitives(self, *, active: bool = True) -> None:
        self.input_session.set_active(active)

    def show_surface(self, state: SurfaceState, tab: int | None = None) -> None:
        self.surface_state = state
        surface_tab = self._active if tab is None else tab
        self.selection.set_options((), f"surface:{surface_tab}")
        self._focus_line = -1
        self.update(state.render(ICON_INDENT), tab=tab)

    def scroll_to_line(self, line: int, tab: int | None = None, margin: int = 3) -> None:
        """滚动使指定行可见（0-indexed），下方保留 margin 行裕度"""
        tab = self._active if tab is None else tab
        vs = self.query_one(f"#t{tab}", VerticalScroll)
        top = vs.scroll_offset.y
        height = vs.size.height
        if line < top:
            vs.scroll_to(
                y=line, animate=False, force=True, immediate=True,
            )
        elif line + margin >= top + height:
            vs.scroll_to(
                y=line + margin - height + 1,
                animate=False,
                force=True,
                immediate=True,
            )

    # ── 导航 ──

    def reset_cursor(self) -> None:
        """重置光标（窗口重新打开时调用）。子类可 super() 后追加逻辑。"""
        self.selection.reset()
        self.confirmation.close()

    def reflow_content(self) -> None:
        """Re-render width-sensitive content without resetting panel state."""

    def on_resize(self, _event) -> None:
        self.call_after_refresh(self.reflow_content)

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

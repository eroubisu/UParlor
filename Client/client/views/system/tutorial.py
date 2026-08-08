"""新手教程 — 交互式逐步引导浮窗

每页是光标列表，用户必须导航到动作项并按 Enter 推进。
第一页选择键位偏好，影响后续页面的按键提示文本。

页面：0 确认操作  1 移动光标  2 文本滚动  3 标签切换
      4 文字输入  5 快捷菜单  6 完成
"""
from __future__ import annotations

from ...window_engine.text import cell_width
from textual.app import ComposeResult
from textual.events import Click, MouseDown, MouseMove
from textual.containers import VerticalScroll
from textual.widgets import Input, Static
from textual.message import Message

from ...widgets.panel import Panel
from ...window_engine import Divider, InputSpec, Option
from ...widgets.window import Window
from ...window_engine import WindowSpec, register_window
from ...config import (
    M_DIM, M_BOLD, M_CMD, M_ONLINE, M_END,
    COLOR_FG_PRIMARY, COLOR_FG_TERTIARY, COLOR_ONLINE,
    ICON_INDENT, NF_ONLINE, NF_OFFLINE, NF_ARROW_R, NF_CHECK,
)

_ARROW_L = '\uf060'  # NF left arrow

# ── Unified nav labels (all pages share these) ──
_LABEL_BACK = f'上一步 {_ARROW_L}'
_LABEL_NEXT = f'下一步 {NF_ARROW_R}'

# ── All-keys hints (show all 3 groups, aligned) ──
_KEYS_VERT = f'{M_DIM}上下移动  {M_CMD}j/k{M_END}{M_DIM}  {M_CMD}↑/↓{M_END}{M_DIM}  {M_CMD}w/s{M_END}'
_KEYS_HORZ_NEXT = f'{M_DIM}下一标签  {M_CMD}l/→/d{M_END}'
_KEYS_HORZ_PREV = f'{M_DIM}上一标签  {M_CMD}h/←/a{M_END}'

# ── Item types ──
TEXT = 'text'
SEP = 'sep'
RADIO = 'radio'
PRACTICE = 'practice'
ACTION = 'action'
BACK = 'back'

# ── Pages ──
_TITLES = ['确认操作', '移动光标', '文本滚动', '标签切换', '面板切换', '文字输入', '快捷菜单', '完成']
_TOTAL = len(_TITLES)
_P_INTRO = 0
_P_SCROLL = 2
_P_TAB = 3
_P_FOCUS = 4
_P_INPUT = 5

# ── Key preferences ──
_PREF = [
    {'label': 'Vim 键位',  'keys': '( j / k / h / l )',
     'dn': 'j', 'up': 'k', 'rt': 'l', 'lt': 'h',
     'alt': '也可用 ↑↓←→ 或 w/s/a/d'},
    {'label': '方向键',    'keys': '( ↑ / ↓ / ← / → )',
     'dn': '↓', 'up': '↑', 'rt': '→', 'lt': '←',
     'alt': '也可用 j/k/h/l 或 w/s/a/d'},
    {'label': 'WASD',      'keys': '( w / s / a / d )',
     'dn': 's', 'up': 'w', 'rt': 'd', 'lt': 'a',
     'alt': '也可用 j/k/h/l 或 ↑↓←→'},
]

# Max CJK width of label column for alignment
_LABEL_W = max(cell_width(p['label']) for p in _PREF)


def _pad(text: str, width: int) -> str:
    return text + ' ' * (width - cell_width(text))


def _radio_label(idx: int) -> str:
    p = _PREF[idx]
    return f"{_pad(p['label'], _LABEL_W)}  {p['keys']}"


def _km(p: int, key: str) -> str:
    return f"{M_CMD}{_PREF[p][key]}{M_END}"


# ── Page builders ──

def _page_intro() -> list[tuple[str, str]]:
    """Page 0: 确认操作 — 教 Enter/z"""
    return [
        # 介绍
        (TEXT, f'{M_BOLD}欢迎来到 UParlor！{M_END}'),
        (TEXT, ''),
        (TEXT, f'本教程将逐步教你如何操作。'),
        (TEXT, f'每一步都需要你完成对应操作才能继续。'),
        (TEXT, ''),
        (TEXT, f'{M_CMD}Enter{M_END} / {M_CMD}z{M_END}  确认选择'),
        (TEXT, f'{M_DIM}这是最基本的操作，整个游戏中都会用到。{M_END}'),
        (SEP, ''),
        # 练习区
        (TEXT, f'{M_BOLD}试试看：按下 {M_CMD}Enter{M_END}{M_BOLD} 或 {M_CMD}z{M_END}{M_BOLD} 开始{M_END}'),
        (SEP, ''),
        # 导航
        (ACTION, f'开始教程 {NF_ARROW_R}'),
    ]


def _page_welcome(pref_set: bool) -> list[tuple[str, str]]:
    """Page 1: 移动光标 — 教上下移动 + 选操作方式"""
    items: list[tuple[str, str]] = [
        # 介绍
        (TEXT, f'以下按键都可以{M_BOLD}上下移动{M_END}光标：'),
        (TEXT, _KEYS_VERT),
        (TEXT, f'{M_DIM}这些按键在整个游戏中通用。{M_END}'),
        (SEP, ''),
        # 练习区
        (TEXT, f'{M_BOLD}移动光标并用 {M_CMD}Enter{M_END}{M_BOLD} 选择操作方式{M_END}'),
        (RADIO, _radio_label(0)),
        (RADIO, _radio_label(1)),
        (RADIO, _radio_label(2)),
        (SEP, ''),
        # 导航
        (BACK, _LABEL_BACK),
    ]
    if pref_set:
        items.append((ACTION, _LABEL_NEXT))
    return items


def _page_tab(p: int) -> list[tuple[str, str]]:
    """Page 3: 标签切换"""
    return [
        # 介绍
        (TEXT, f'切换标签页：'),
        (TEXT, _KEYS_HORZ_NEXT),
        (TEXT, _KEYS_HORZ_PREV),
        (TEXT, f'{M_DIM}这些按键也是通用的。{M_END}'),
        (SEP, ''),
        # 练习区
        (TEXT, f'{M_BOLD}切换到「练习」标签{M_END}'),
        (SEP, ''),
        # 导航
        (BACK, _LABEL_BACK),
    ]


def _page_tab_t1(p: int) -> list[tuple[str, str]]:
    return [
        (TEXT, '切换成功！'),
        (SEP, ''),
        (ACTION, _LABEL_NEXT),
    ]


def _page_focus() -> list[tuple[str, str]]:
    """Page 4: 面板切换（左侧面板内容）"""
    return [
        # 介绍
        (TEXT, f'方向键只在当前面板内导航'),
        (TEXT, f'{M_CMD}Shift+方向键{M_END} 切换面板'),
        (TEXT, f'{M_DIM}大写 {M_CMD}W/A/S/D{M_END}{M_DIM}、{M_CMD}H/J/K/L{M_END}{M_DIM} 与其同效{M_END}'),
        (SEP, ''),
        # 练习区
        (TEXT, f'{M_BOLD}切换到右侧面板{M_END}'),
        (SEP, ''),
        # 导航
        (BACK, _LABEL_BACK),
    ]


def _page_input(p: int, messages: list[str]) -> list[tuple[str, str]]:
    """Page 5: 文字输入"""
    items: list[tuple[str, str]] = [
        # 介绍
        (TEXT, f'{M_CMD}i{M_END}  进入输入模式，{M_CMD}Enter{M_END} 发送'),
        (TEXT, f'{M_DIM}大写 {M_CMD}I{M_END}{M_DIM} = 持续输入（发送后不关闭输入框）{M_END}'),
        (SEP, ''),
        # 练习区
        (TEXT, f'{M_BOLD}发送至少 1 条消息{M_END}'),
    ]
    if messages:
        items.append((SEP, ''))
        for msg in messages:
            items.append((TEXT, f'{M_ONLINE}{NF_CHECK}{M_END} {msg}'))
    items.append((SEP, ''))
    # 导航
    items.append((BACK, _LABEL_BACK))
    if messages:
        items.append((ACTION, _LABEL_NEXT))
    return items


def _page_space(p: int) -> list[tuple[str, str]]:
    """Page 6: root menu"""
    return [
        # 介绍
        (TEXT, f'{M_DIM}功能菜单集中了常用入口。{M_END}'),
        (TEXT, f'{M_DIM}注意：开始界面无法使用，进入游戏后可体验。{M_END}'),
        (SEP, ''),
        # 说明区
        (TEXT, f'{M_CMD}Space{M_END}  打开功能菜单'),
        (TEXT, f'{M_DIM}使用方向键移动并确认选择，不使用字母快捷项。{M_END}'),
        (SEP, ''),
        # 导航
        (BACK, _LABEL_BACK),
        (ACTION, _LABEL_NEXT),
    ]


def _page_done(p: int) -> list[tuple[str, str]]:
    """Page 7: 完成"""
    return [
        (TEXT, f'{M_BOLD}基础教程完成！{M_END}'),
        (SEP, ''),
        (TEXT, f'按 {M_CMD}Esc{M_END} 退出教程'),
        (TEXT, f'{M_DIM}进入游戏后可从 {M_CMD}Space{M_END}{M_DIM} 菜单选择“设置”，再选择“打开文档”。{M_END}'),
        (SEP, ''),
        # 导航
        (BACK, _LABEL_BACK),
    ]


_BUILDERS = [_page_intro, _page_welcome, None, _page_tab, None, None, _page_space, _page_done]

# ── Scroll page ──
_SCROLL_TMPL = """\
{dim}上下滚动  {cmd}j/k{end}{dim}  {cmd}↑/↓{end}{dim}  {cmd}w/s{end}
{sep}
试试向下滚动




{sep}
继续……




{sep}
再往下一点




{sep}
快到底了




{sep}


{sep}
{dim}到底了！按 {cmd}Enter{end}{dim} 继续{end}
{dim}按 {cmd}h{end}{dim}/{cmd}←{end}{dim} 返回上一步{end}"""


class TutorialPanel(Panel):
    """交互式教程面板"""

    class TutorialDone(Message):
        """教程完成"""

    icon_align = True
    hide_scrollbar = True
    has_input = True
    tabs = ['引导', '练习']
    placeholder = '输入任意文字，按 Enter 发送'

    def __init__(self, **kw):
        super().__init__(**kw)
        self._page: int = 0
        self._pref: int = 0
        self._pref_set: bool = False
        self._items: list[tuple[str, str]] = []
        self._checked: set[int] = set()
        self._on_tab1: bool = False
        self._input_ready: bool = False
        self._messages: list[str] = []

    def compose_content(self) -> ComposeResult:
        for index in range(2):
            with VerticalScroll(classes="tab", id=f"t{index}"):
                yield Static(
                    "", id=f"tutorial-before-{index}",
                    classes="content icon-align", markup=True,
                )
                yield Divider(id=f"tutorial-divider-{index}")
                yield Static(
                    "", id=f"tutorial-after-{index}",
                    classes="tutorial-after icon-align", markup=True,
                )

    def on_mount(self) -> None:
        super().on_mount()
        for t in self.query('.tab'):
            t.can_focus = False
        self.activate_input_context()
        self.call_after_refresh(self._build_page)

    def reflow_content(self) -> None:
        self._build_page()

    def reset_cursor(self) -> None:
        self._page = 0
        super().reset_cursor()
        self._pref = 0
        self._pref_set = False
        self._checked.clear()
        self._on_tab1 = False
        self._input_ready = False
        self._messages.clear()
        if self.is_mounted:
            self.activate_input_context()
        if self._active != 0:
            self.switch_tab(0)
        self._update_title()
        self.call_after_refresh(self._build_page)

    def on_click(self, event: Click) -> None:
        event.stop()
        event.prevent_default()

    def on_mouse_down(self, event: MouseDown) -> None:
        event.stop()
        event.prevent_default()

    def on_mouse_move(self, event: MouseMove) -> None:
        event.stop()
        event.prevent_default()

    def input_spec(self) -> InputSpec:
        available = self._page == _P_INPUT and self._input_ready
        return InputSpec(
            context_id="tutorial:practice-input",
            placeholder=self.placeholder,
            visible=available,
            enabled=available,
            focus=True,
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._page != _P_INPUT:
            return
        text = self.submit_input(event, clear=True).strip()
        if not text:
            return
        self._messages.append(text)
        screen = self.app.screen
        sticky = getattr(screen, '_sticky_insert', False)
        if sticky:
            # 大写 I: 保持输入框打开，只刷新页面
            self._build_page()
        else:
            self._build_page()

    # ── Navigation ──

    def nav(self, action: str) -> None:
        # Scroll page: up/down = scroll, enter = next, tab_prev = back
        if self._page == _P_SCROLL:
            if action in ('up', 'down'):
                super().nav(action)
            elif action == 'enter':
                self._goto_page(_P_TAB)
            elif action == 'tab_prev':
                self._goto_page(1)
            return

        # Tab page: h/l switch tabs, items change per tab
        if self._page == _P_TAB:
            if action == 'tab_next' and not self._on_tab1:
                self._on_tab1 = True
                self.switch_tab(1)
                self._update_title()
                self._items = _page_tab_t1(self._pref)
                self.call_after_refresh(lambda: self._redraw(tab=1))
                return
            if action == 'tab_prev':
                if self._on_tab1:
                    self._on_tab1 = False
                    self.switch_tab(0)
                    self._update_title()
                    self._items = _page_tab(self._pref)
                    self.call_after_refresh(lambda: self._redraw(tab=0))
                return

        match action:
            case 'down':
                self._skip_cursor(1)
            case 'up':
                self._skip_cursor(-1)
            case 'enter':
                self._activate()

    def _skip_cursor(self, delta: int) -> None:
        if self.selection.move(delta):
            self._redraw()

    def _activate(self) -> None:
        selected = self.selected_option
        if selected is None:
            return
        index = int(selected.id)
        typ, _ = self._items[index]

        if typ == RADIO:
            radio_idx = [i for i, (t, _) in enumerate(self._items) if t == RADIO]
            self._pref = radio_idx.index(index)
            old_set = self._pref_set
            self._pref_set = True
            if not old_set:
                # 首次选择 → 重建页面以显示"下一步"
                self._build_page()
            else:
                self._redraw()
            return

        if typ == PRACTICE:
            self._checked ^= {index}
            self._redraw()
            return

        if typ == BACK:
            if self._page > _P_INTRO:
                self._goto_page(self._page - 1)
            return

        if typ != ACTION:
            return

        match self._page:
            case 0:  # intro
                self._goto_page(1)
            case 1:  # welcome
                self._goto_page(_P_SCROLL)
            case 3:  # tab (action is on tab1)
                self._goto_page(_P_FOCUS)
            case 5:  # input — need ≥1 message
                if not self._messages:
                    return
                self._goto_page(6)
            case 6:  # space
                self._goto_page(7)

    # ── Page management ──

    def _goto_page(self, page: int) -> None:
        self._page = page
        self._checked.clear()
        self._on_tab1 = False
        self._input_ready = page == _P_INPUT
        # 显示/隐藏面板切换练习的目标面板 + 确保焦点回到主面板
        window = self.parent
        if isinstance(window, TutorialWindow):
            window._set_focus_target(page == _P_FOCUS)
            if window._focus_pos != (0, 0):
                window.reset_focus()
        self.activate_input_context()
        if self._active != 0:
            self.switch_tab(0)
        self._update_title()
        self._build_page()

    def _build_page(self) -> None:
        if self._page == _P_SCROLL:
            self._items = []
            self.selection.set_options((), f"tutorial:{self._page}")
            self._set_scrollbar(True)
            self.call_after_refresh(self._redraw_scroll)
            return
        self._set_scrollbar(False)
        # Input page uses special builder
        if self._page == _P_INPUT:
            self._items = _page_input(self._pref, self._messages)
            self.call_after_refresh(self._redraw)
            return
        # Focus page uses special builder
        if self._page == _P_FOCUS:
            self._items = _page_focus()
            self._redraw()
            return
        builder = _BUILDERS[self._page]
        if builder is None:
            return
        if self._page == 0:
            self._items = builder()
        elif self._page == 1:
            self._items = builder(self._pref_set)
        else:
            self._items = builder(self._pref)
        self._redraw()

    def _update_title(self) -> None:
        n = self._page + 1
        title = _TITLES[self._page]
        if self._page == _P_TAB:
            self.border_title = f'({n}/{_TOTAL}) {title}  {self._render_tabs()}'
        else:
            self.border_title = f'({n}/{_TOTAL}) {title}'

    def _set_scrollbar(self, visible: bool) -> None:
        self.set_scrollbar_visible(visible)

    # ── Rendering ──

    def _redraw(self, tab: int | None = None) -> None:
        radio_idx = [i for i, (t, _) in enumerate(self._items) if t == RADIO]
        target = tab if tab is not None else (1 if self._on_tab1 else 0)
        options = []
        for index, (typ, label) in enumerate(self._items):
            if typ == RADIO:
                selected = radio_idx.index(index) == self._pref and self._pref_set
                dot = (
                    f"[{COLOR_ONLINE}]{NF_ONLINE}[/]"
                    if selected else NF_OFFLINE
                )
                rendered_label = f"{dot} {label}"
            elif typ == PRACTICE:
                dot = (
                    f"[{COLOR_ONLINE}]{NF_ONLINE}[/]"
                    if index in self._checked else NF_OFFLINE
                )
                rendered_label = f"{dot} {label}"
            else:
                rendered_label = label
            options.append(Option(
                str(index),
                rendered_label,
                enabled=typ not in (TEXT, SEP),
                data=(typ, label),
                markup=True,
            ))
        self.set_options(
            options, f"tutorial:{self._page}:{target}",
        )
        before: list[str] = []
        after: list[str] = []
        lines = before
        has_divider = False

        for i, (typ, label) in enumerate(self._items):
            if typ == TEXT:
                lines.append(label)
            elif typ == SEP:
                has_divider = True
                lines = after
            else:
                lines.extend(self.selection.render_option(
                    options[i],
                    self._content_width(target),
                    idle_prefix=ICON_INDENT,
                    selected_style=f"bold {COLOR_FG_PRIMARY}",
                    idle_style=COLOR_FG_TERTIARY,
                ))

        self.query_one(
            f"#tutorial-before-{target}", Static,
        ).update("\n".join(before))
        self.query_one(
            f"#tutorial-divider-{target}", Divider,
        ).display = has_divider
        self.query_one(
            f"#tutorial-after-{target}", Static,
        ).update("\n".join(after))

    def _redraw_scroll(self) -> None:
        before, after = _SCROLL_TMPL.split("{sep}", 1)
        values = {"dim": M_DIM, "end": M_END, "cmd": M_CMD}
        self.query_one("#tutorial-before-0", Static).update(
            before.format(**values))
        self.query_one("#tutorial-divider-0", Divider).display = True
        self.query_one("#tutorial-after-0", Static).update(
            after.format(**values))


class _FocusTarget(Panel):
    """面板切换练习的目标面板，支持交互"""

    icon_align = True
    border_title = '目标'
    _arrived: bool = False

    def on_mount(self) -> None:
        super().on_mount()
        self._show_waiting()

    def _show_waiting(self) -> None:
        """等待用户切换到此面板"""
        self._arrived = False
        self.update(f'{ICON_INDENT}{M_DIM}切换到该面板{M_END}')

    def _show_success(self) -> None:
        """用户已切换到此面板，显示下一步"""
        self._arrived = True
        self.set_options(
            (Option("next", _LABEL_NEXT),),
            "tutorial-focus-target",
        )
        self.update(
            f'{ICON_INDENT}{M_ONLINE}{NF_CHECK}{M_END} 切换成功！\n'
            f'\n'
            f'{self.render_options()}'
        )

    def on_panel_focus(self) -> None:
        """被 Window.focus_move 聚焦时触发"""
        if not self._arrived:
            self._show_success()

    def nav(self, action: str) -> None:
        if action == 'enter' and self._arrived:
            window = self.parent
            if isinstance(window, TutorialWindow):
                tp = window._panels.get('tutorial-panel')
                if tp:
                    tp._goto_page(_P_INPUT)
            return
        super().nav(action)


class TutorialWindow(Window):
    """新手教程主窗口"""

    DEFAULT_CSS = """
    TutorialWindow {
        layer: floating;
        width: 62%;
        height: 62%;
        align: center middle;
    }
    TutorialWindow > #tutorial-panel {
        width: 44;
        height: 100%;
    }
    TutorialWindow > #focus-target {
        width: 20;
        height: 100%;
        display: none;
    }
    """

    focus_grid = [["tutorial-panel", "focus-target"]]

    # WindowEngine 主窗口 (教程 - 未完成时走这条)
    spec = WindowSpec(
        id="tutorial-window", title="教程",
        group="primary", mode="primary", order=5,
    )

    def compose(self) -> ComposeResult:
        yield TutorialPanel(id="tutorial-panel")
        yield _FocusTarget(id="focus-target")

    def _set_focus_target(self, visible: bool) -> None:
        """显示/隐藏右侧练习面板"""
        ft = self._panels.get('focus-target')
        if not ft:
            return
        if visible:
            ft._show_waiting()
            ft.styles.display = 'block'
        else:
            ft.styles.display = 'none'

    def focus_move(self, direction: str) -> None:
        # 仅在面板切换练习页允许切换
        panel = self._panels.get('tutorial-panel')
        if panel and panel._page == _P_FOCUS:
            super().focus_move(direction)

    def on_click(self, event: Click) -> None:
        event.stop()

    def on_mouse_down(self, event: MouseDown) -> None:
        event.stop()

    def on_mouse_move(self, event: MouseMove) -> None:
        event.stop()


register_window(TutorialWindow)

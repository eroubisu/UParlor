"""LoginPanel — 登录面板（开始/注册/设置 三标签页）"""

from __future__ import annotations

from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import RichLog, Static
from textual.widget import Widget

from ..config import (
    M_DIM, M_BOLD, M_END, VERSION,
    COLOR_FG_PRIMARY, COLOR_FG_SECONDARY, COLOR_ACCENT,
)
from ..widgets.input_bar import InputBar, InputTextArea
from ..widgets.helpers import render_tab_header
from ..widgets.prompt import InputBarMixin
from ..state import ModuleStateManager

_WELCOME_DOC = """\

[bold]全局操作逻辑[/bold]

            [bold]←[/bold]    [bold]↓[/bold]    [bold]↑[/bold]    [bold]→[/bold]
窗口内部    [bold]h[/bold]    [bold]j[/bold]    [bold]k[/bold]    [bold]l[/bold]
窗口外部    [bold]H[/bold]    [bold]J[/bold]    [bold]K[/bold]    [bold]L[/bold]
            
打开输入    [bold]i[/bold]
确认选中    [bold]Enter[/bold]
返回        [bold]Backspace[/bold]
退出        [bold]Esc[/bold]

打开菜单    [bold]Space[/bold]
补全/切换   [bold]Tab[/bold]
多选模式    [bold]v[/bold]



[dim]账号 英文/数字 2—12位  密码 ≥ 3位[/dim]

按 [bold]i[/bold] 输入账号\
"""

_TABS = ['login', 'register', 'settings']
_TAB_LABELS = {'login': '登录', 'register': '注册', 'settings': '设置'}

_SETTINGS_OPTIONS = [
    ('quit', '退出程序'),
]

_SETTINGS_MODE_LIST = 'list'
_SETTINGS_MODE_CONFIRM = 'confirm'


class LoginPanel(InputBarMixin, Widget):
    """登录面板：三标签页（开始/注册/设置）"""

    _input_bar_id = "login-input-bar"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._tab: str = 'login'
        self._settings_cursor: int = 0
        self._settings_mode: str = _SETTINGS_MODE_LIST

    def compose(self) -> ComposeResult:
        yield Static(id="login-header", markup=True)
        with VerticalScroll(id="login-doc"):
            yield Static(_WELCOME_DOC, markup=True)
        yield RichLog(
            id="login-settings", wrap=True, highlight=True,
            markup=True, max_lines=50, min_width=0,
        )
        yield Static("", id="login-prompt-text", markup=True)
        yield InputBar(prompt_id="login-prompt", id="login-input-bar")

    def on_input_submit(self, text: str):
        if self._tab == 'settings' or not text:
            return
        self.app.network.send({"type": self._tab, "text": text})

    def on_mount(self) -> None:
        self._render_header()
        self._sync_content_visibility()

    def _render_header(self):
        render_tab_header(self, "login-header", _TABS, _TAB_LABELS, self._tab)

    # ── 标签页切换 ──

    def nav_tab_next(self):
        idx = _TABS.index(self._tab)
        self._tab = _TABS[(idx + 1) % len(_TABS)]
        self._on_tab_change()

    def nav_tab_prev(self):
        idx = _TABS.index(self._tab)
        self._tab = _TABS[(idx - 1) % len(_TABS)]
        self._on_tab_change()

    def _on_tab_change(self):
        self._render_header()
        self._sync_content_visibility()
        if self._tab == 'settings':
            self._settings_cursor = 0
            self._settings_mode = _SETTINGS_MODE_LIST
            self._render_settings()
            self.add_message('')
        else:
            self.add_message('请输入用户名：')

    def _sync_content_visibility(self):
        """切换标签时显示/隐藏对应内容区"""
        try:
            doc = self.query_one("#login-doc", VerticalScroll)
            log = self.query_one("#login-settings", RichLog)
            if self._tab == 'settings':
                doc.display = False
                log.display = True
            else:
                doc.display = True
                log.display = False
        except Exception:
            pass

    # ── 设置标签页 ──

    def _render_settings(self):
        try:
            log: RichLog = self.query_one("#login-settings", RichLog)
        except Exception:
            return
        log.clear()

        if self._settings_mode == _SETTINGS_MODE_LIST:
            for i, (_, label) in enumerate(_SETTINGS_OPTIONS):
                if i == self._settings_cursor:
                    log.write(RichText.from_markup(
                        f"  [{COLOR_ACCENT}]●[/] {M_BOLD}{label}{M_END}"))
                else:
                    log.write(RichText.from_markup(
                        f"    [{COLOR_FG_SECONDARY}]{label}[/]"))
            log.write("")
            log.write(RichText.from_markup(
                f"  {M_DIM}v{VERSION or 'dev'}{M_END}"))
        elif self._settings_mode == _SETTINGS_MODE_CONFIRM:
            _, label = _SETTINGS_OPTIONS[self._settings_cursor]
            log.write(RichText.from_markup(
                f"  {M_DIM}确定{label}？{M_END}"))
            log.write(RichText.from_markup(
                f"  {M_DIM}Enter 确认  /  Backspace 取消{M_END}"))

    # ── 导航 ──

    def nav_down(self):
        if self._tab == 'settings' and self._settings_mode == _SETTINGS_MODE_LIST:
            self._settings_cursor = (self._settings_cursor + 1) % len(_SETTINGS_OPTIONS)
            self._render_settings()
            return
        try:
            self.query_one("#login-doc", VerticalScroll).scroll_down(animate=False)
        except Exception:
            pass

    def nav_up(self):
        if self._tab == 'settings' and self._settings_mode == _SETTINGS_MODE_LIST:
            self._settings_cursor = (self._settings_cursor - 1) % len(_SETTINGS_OPTIONS)
            self._render_settings()
            return
        try:
            self.query_one("#login-doc", VerticalScroll).scroll_up(animate=False)
        except Exception:
            pass

    def nav_enter(self):
        if self._tab != 'settings':
            return
        if self._settings_mode == _SETTINGS_MODE_LIST:
            action_id, _ = _SETTINGS_OPTIONS[self._settings_cursor]
            if action_id == 'quit':
                self._settings_mode = _SETTINGS_MODE_CONFIRM
                self._render_settings()
        elif self._settings_mode == _SETTINGS_MODE_CONFIRM:
            action_id, _ = _SETTINGS_OPTIONS[self._settings_cursor]
            if action_id == 'quit':
                self.app.action_quit()

    def nav_back(self) -> bool:
        if self._tab == 'settings' and self._settings_mode == _SETTINGS_MODE_CONFIRM:
            self._settings_mode = _SETTINGS_MODE_LIST
            self._render_settings()
            return True
        return False

    def add_message(self, text: str):
        try:
            self.query_one("#login-prompt-text", Static).update(text)
        except Exception:
            pass

    def on_resize(self, event) -> None:
        self._render_header()

    def restore(self, state: ModuleStateManager):
        pass

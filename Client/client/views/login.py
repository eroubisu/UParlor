"""登录画面 — LoginWindow > LoginPanel"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static, Input
from textual.containers import VerticalScroll
from textual.message import Message

from ..widgets.panel import Panel
from ..widgets.window import Window
from ..config import (
    M_DIM, M_BOLD, M_CMD, M_END,
    NF_KEY, NF_USERS, NF_GEAR,
    COLOR_FG_PRIMARY, COLOR_FG_TERTIARY,
    DEFAULT_HOST,
)
from .system.settings import _OPTIONS as _ALL_SETTINGS

# 登录页设置只显示教程（排除 profile 和 docs）
_LOGIN_SETTINGS = [(k, n) for k, n in _ALL_SETTINGS if k not in ('profile', 'docs')]

# ── 常量 ──

_TABS = ['login', 'register', 'settings']
_TAB_LABELS = {
    'login': f'{NF_KEY} 登录',
    'register': f'{NF_USERS} 注册',
    'settings': f'{NF_GEAR} 设置',
}

# 服务端密码提示前缀
_PASSWORD_PROMPTS = ('请输入密码', '请设置密码')

_STEP_USERNAME = 'username'
_STEP_PASSWORD = 'password'
_STEP_WAITING = 'waiting'

_LOGO = """\
 ██╗   ██╗██████╗  █████╗ ██████╗ ██╗      ██████╗ ██████╗
 ██║   ██║██╔══██╗██╔══██╗██╔══██╗██║     ██╔═══██╗██╔══██╗
 ██║   ██║██████╔╝███████║██████╔╝██║     ██║   ██║██████╔╝
 ██║   ██║██╔═══╝ ██╔══██║██╔══██╗██║     ██║   ██║██╔══██╗
 ╚██████╔╝██║     ██║  ██║██║  ██║███████╗╚██████╔╝██║  ██║
  ╚═════╝ ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝"""

_WELCOME_DOC = "[#243F42]" + _LOGO + "[/]"


# ── LoginPanel ──

class LoginPanel(Panel):
    """登录面板：三标签页（登录/注册/设置）"""

    class OpenGuide(Message):
        """请求打开教程或文档窗口"""
        def __init__(self, target: str) -> None:
            super().__init__()
            self.target = target

    has_input = True
    placeholder = "请输入用户名"
    hide_scrollbar = True

    def __init__(self, **kw):
        tabs = [_TAB_LABELS[t] for t in _TABS]
        super().__init__(tabs=tabs, **kw)
        self._tab: str = 'login'
        self._step: str = _STEP_USERNAME
        self._submitted: bool = False

    def compose_content(self) -> ComposeResult:
        with VerticalScroll(classes="tab", id="t0"):
            yield Static(_WELCOME_DOC, classes="content", markup=True)
        with VerticalScroll(classes="tab", id="t1"):
            yield Static(_WELCOME_DOC, classes="content", markup=True)
        with VerticalScroll(classes="tab", id="t2"):
            yield Static("", classes="content", markup=True)

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#t2 .content").add_class("icon-align")
        self._render_settings()

    # ── INSERT 协议 ──

    def get_input_widget(self) -> Input | None:
        if self._tab in ('login', 'register'):
            return self.query_one("#input", Input)
        return None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self._submitted:
            event.stop()
            return
        self.app.network.send({"type": self._tab, "text": text})
        self._submitted = True
        if self._step == _STEP_USERNAME:
            self._pending_username = text
            self._step = _STEP_WAITING
            event.input.placeholder = "请稍候..."
        elif self._step == _STEP_PASSWORD:
            self._step = _STEP_WAITING
            event.input.placeholder = "请稍候..."
        event.stop()

    # ── 服务端消息 ──

    def add_message(self, text: str) -> None:
        """dispatch.py 调用 — 显示服务端登录提示并更新状态机"""
        inp = self.query_one("#input", Input)
        # 密码提示
        if any(text.startswith(p) for p in _PASSWORD_PROMPTS):
            self._step = _STEP_PASSWORD
            self._submitted = False
            inp.placeholder = "请输入密码"
            inp.password = True
        elif self._step == _STEP_WAITING:
            self._submitted = False
            if inp.password:
                # 密码错误 — 服务端仍在 password 状态，保持密码模式
                self._step = _STEP_PASSWORD
                inp.placeholder = "请输入密码"
            else:
                self._step = _STEP_USERNAME
                inp.placeholder = "请输入用户名"
                inp.password = False

    # ── 导航 ──

    def nav(self, action: str) -> None:
        match action:
            case "tab_next":
                idx = _TABS.index(self._tab)
                self._tab = _TABS[(idx + 1) % len(_TABS)]
                self.switch_tab(_TABS.index(self._tab))
                self._sync_input()
            case "tab_prev":
                idx = _TABS.index(self._tab)
                self._tab = _TABS[(idx - 1) % len(_TABS)]
                self.switch_tab(_TABS.index(self._tab))
                self._sync_input()
            case "down" if self._tab == 'settings':
                if self._move_cursor(1, len(_LOGIN_SETTINGS)):
                    self._render_settings()
            case "up" if self._tab == 'settings':
                if self._move_cursor(-1, len(_LOGIN_SETTINGS)):
                    self._render_settings()
            case "enter" if self._tab == 'settings':
                target = _LOGIN_SETTINGS[self._cursor][0]
                self.post_message(self.OpenGuide(target))
            case _:
                super().nav(action)

    def _render_settings(self) -> None:
        labels = [name for _, name in _LOGIN_SETTINGS]
        self.update(self._render_cursor_items(labels), tab=2)

    def _sync_input(self):
        """切换标签时同步输入框状态"""
        row = self.query_one("#input-row")
        inp = self.query_one("#input", Input)
        if self._tab == 'settings':
            row.display = False
        else:
            row.display = True
            self._step = _STEP_USERNAME
            inp.disabled = False
            inp.placeholder = "请输入用户名"
            inp.password = False
            inp.value = ""

    def restore(self, state) -> None:
        pass


# ── LoginWindow ──

class LoginWindow(Window):
    """登录窗口 — 紧凑居中，包含单个 LoginPanel"""

    DEFAULT_CSS = """
    LoginWindow {
        width: 1fr;
        height: 1fr;
        align: center middle;
    }
    LoginWindow > #login-panel {
        width: 68;
        height: 12;
    }
    LoginWindow > #login-panel > .tab > .content {
        padding: 1 2 0 3;
    }
    LoginWindow > #login-panel > .tab > .content.icon-align {
        padding: 0;
    }
    """

    focus_grid = [["login-panel"]]

    def compose(self) -> ComposeResult:
        yield LoginPanel(id="login-panel")

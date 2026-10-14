"""登录画面 — LoginWindow > LoginPanel"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static, Input
from textual.containers import VerticalScroll
from textual.message import Message

from ..widgets.panel import Panel
from ..widgets.window import Window
from ..window_engine import InputSpec, Option
from ..window_engine import WindowSpec, register_window
from ..window_specs import bind_state
from ..config import (
    NF_KEY, NF_USERS, NF_GEAR,
)

# Login exposes only the guide needed before entering the application.
_LOGIN_SETTINGS = [("tutorial", "打开教程")]

# ── 常量 ──

_TABS = ['login', 'register', 'settings']
_TAB_LABELS = {
    'login': f'{NF_KEY} 登录',
    'register': f'{NF_USERS} 注册',
    'settings': f'{NF_GEAR} 设置',
}

# 服务端密码提示前缀
_PASSWORD_PROMPTS = ('请输入密码', '请设置密码')
_USERNAME_PROMPTS = ('请输入用户名',)
_PLAIN_STEP_PROMPTS = (
    '请输入用户名：',
    '请输入密码：',
    '请设置密码（至少3个字符）：',
)

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
        self._waiting_for: str = ""
        self._submitted: bool = False
        self._placeholder_override = ""
        self._auth_state = None

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

    def input_spec(self) -> InputSpec:
        interactive = (
            self._tab in ("login", "register")
            and not self._submitted
            and not (self._auth_state and self._auth_state.active)
        )
        if self._step == _STEP_PASSWORD:
            placeholder = "请输入密码"
            password = True
        elif self._step == _STEP_WAITING:
            placeholder = "请稍候..."
            password = False
        else:
            placeholder = "请输入用户名"
            password = False
        placeholder = getattr(self, "_placeholder_override", "") or placeholder
        return InputSpec(
            context_id=f"login:{self._tab}:{self._step}",
            placeholder=placeholder,
            visible=self._tab in ("login", "register"),
            enabled=interactive,
            password=password,
            focus=True,
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = self.submit_input(event, clear=True).strip()
        if not text or self._submitted:
            return
        self.app.network.send({"type": self._tab, "text": text})
        self._placeholder_override = ""
        self._submitted = True
        if self._step == _STEP_USERNAME:
            self._pending_username = text
            self._waiting_for = _STEP_USERNAME
            self._step = _STEP_WAITING
        elif self._step == _STEP_PASSWORD:
            self._waiting_for = _STEP_PASSWORD
            self._step = _STEP_WAITING
        self.activate_input_context()

    # ── 服务端消息 ──

    def bind_state(self, state) -> None:
        if self._auth_state is state.auth:
            return
        if self._auth_state is not None:
            self._auth_state.remove_listener(self._on_auth_event)
        self._auth_state = state.auth
        self._auth_state.add_listener(self._on_auth_event)
        self._render_auth_state()

    def _on_auth_event(self, _event: str, *_args) -> None:
        self._render_auth_state()

    def _render_auth_state(self) -> None:
        if self._auth_state is None or not self._auth_state.active:
            self.update(_WELCOME_DOC, tab=0)
            self.activate_input_context()
            return
        self.set_options(
            (Option(
                str(choice.get("id", index)),
                str(choice.get("label", "")),
            ) for index, choice in enumerate(self._auth_state.choices)),
            "login-auth-conflict",
        )
        selected_id = self._auth_state.selected_id()
        if selected_id:
            self.selection.select(selected_id)
        self.update(
            f"{self._auth_state.text}\n\n{self.render_options()}",
            tab=0,
        )
        self._submitted = False
        self.activate_input_context()

    def _send_auth_conflict_response(self, choice: str) -> None:
        self.app.network.send({
            'type': 'auth_conflict_response',
            'choice': choice,
        })

    def add_message(self, text: str) -> None:
        """net/dispatch 调用 — 显示服务端登录提示并更新状态机"""
        is_plain_step = text in _PLAIN_STEP_PROMPTS
        feedback = "" if is_plain_step else text.splitlines()[0]
        # 密码提示
        if any(text.startswith(p) for p in _PASSWORD_PROMPTS):
            self._step = _STEP_PASSWORD
            self._waiting_for = ""
            self._submitted = False
            self._placeholder_override = feedback
        elif any(prompt in text for prompt in _USERNAME_PROMPTS):
            self._step = _STEP_USERNAME
            self._waiting_for = ""
            self._submitted = False
            self._placeholder_override = feedback
        elif self._step == _STEP_WAITING:
            self._submitted = False
            if self._waiting_for == _STEP_PASSWORD:
                # 密码错误 — 服务端仍在 password 状态，保持密码模式
                self._step = _STEP_PASSWORD
                self._placeholder_override = feedback
            else:
                self._step = _STEP_USERNAME
                self._placeholder_override = feedback
            self._waiting_for = ""
        if self._tab in ("login", "register"):
            self.update(_WELCOME_DOC, tab=_TABS.index(self._tab))
        self.activate_input_context()

    def return_to_username(self) -> bool:
        """取消密码阶段，并等待服务端恢复用户名输入状态。"""
        if self._tab not in ("login", "register"):
            return False
        if self._step != _STEP_PASSWORD or self._submitted:
            return False
        if not self.app.network.send({"type": "auth_cancel"}):
            return False
        self._submitted = True
        self._step = _STEP_WAITING
        self._waiting_for = _STEP_PASSWORD
        self._placeholder_override = "正在返回用户名输入..."
        self.update(_WELCOME_DOC, tab=_TABS.index(self._tab))
        self.activate_input_context()
        return True

    def _cancel_pending_auth(self) -> None:
        """离开认证标签时同步取消服务端的未完成认证状态。"""
        if (
            self._tab in ("login", "register")
            and (self._step != _STEP_USERNAME or self._submitted)
        ):
            self.app.network.send({"type": "auth_cancel"})

    def reset_session(self) -> None:
        """Restore the login form after the previous account session ends."""
        self._tab = 'login'
        self._step = _STEP_USERNAME
        self._waiting_for = ""
        self._submitted = False
        self._placeholder_override = ""
        self.switch_tab(0)
        self.input_session.clear()
        self.activate_input_context()
        self.update(_WELCOME_DOC, tab=0)

    # ── 导航 ──

    def _nav_auth_conflict(self, action: str) -> None:
        direction = {'up': -1, 'down': 1}.get(action)
        if direction is not None:
            if self.selection.move(direction):
                self._auth_state.move(direction)
            return
        if action != 'enter' or self._submitted:
            return
        selected = self.selected_option
        choice = selected.id if selected is not None else ""
        if choice:
            self._submitted = True
            self._send_auth_conflict_response(choice)

    def _switch_login_tab(self, offset: int) -> None:
        self._cancel_pending_auth()
        current_index = _TABS.index(self._tab)
        target_index = (current_index + offset) % len(_TABS)
        self._tab = _TABS[target_index]
        self._step = _STEP_USERNAME
        self._waiting_for = ""
        self._submitted = False
        self._placeholder_override = ""
        self.switch_tab(target_index)
        if self._tab in ("login", "register"):
            self.update(_WELCOME_DOC, tab=target_index)
        if self._tab == "settings":
            self._render_settings()

    def _nav_settings(self, action: str) -> bool:
        direction = {'up': -1, 'down': 1}.get(action)
        if direction is not None:
            if self.selection.move(direction):
                self._render_settings()
            return True
        if action != 'enter':
            return False
        selected = self.selected_option
        if selected is not None:
            self.post_message(self.OpenGuide(selected.id))
        return True

    def nav(self, action: str) -> None:
        if self._auth_state is not None and self._auth_state.active:
            self._nav_auth_conflict(action)
            return
        if action == "tab_next":
            self._switch_login_tab(1)
            return
        if action == "tab_prev":
            self._switch_login_tab(-1)
            return
        if self._tab == 'settings' and self._nav_settings(action):
            return
        super().nav(action)

    def _render_settings(self) -> None:
        self.set_options(
            (Option(option_id, label) for option_id, label in _LOGIN_SETTINGS),
            "login-settings",
        )
        self.update(self.render_options(), tab=2)

    def reflow_content(self) -> None:
        if self._auth_state is not None and self._auth_state.active:
            self.update(
                f"{self._auth_state.text}\n\n{self.render_options()}",
                tab=0,
            )
        elif self._tab == "settings":
            self._render_settings()

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

    # WindowEngine 主窗口 (未登录状态)
    spec = WindowSpec(
        id="login-window", title="登录",
        group="primary", mode="primary", order=10,
        bind=bind_state,
    )

    def compose(self) -> ComposeResult:
        yield LoginPanel(id="login-panel")

    def bind_state(self, state) -> None:
        self.query_one("#login-panel", LoginPanel).bind_state(state)

    def reset_session(self) -> None:
        self.query_one("#login-panel", LoginPanel).reset_session()


register_window(LoginWindow)

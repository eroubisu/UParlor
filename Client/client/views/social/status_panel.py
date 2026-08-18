"""状态面板 — 左右对齐的玩家信息展示"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static
from rich.table import Table
from rich.console import Group

from ...config import (
    COLOR_FG_PRIMARY, COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    COLOR_BORDER, ICON_INDENT,
    NF_LEVEL, NF_COIN, NF_STAR, NF_HEART, NF_CALENDAR,
    M_DIM, M_END,
)
from ...widgets.panel import Panel
from ...window_engine import Option

_BAR_DONE = '━'
_BAR_TODO = '━'
_BAR_LEN = 16


def _make_table() -> Table:
    t = Table(
        show_header=False, show_edge=False,
        box=None, expand=True, padding=(0, 0), pad_edge=False,
    )
    t.add_column(no_wrap=True)
    t.add_column(justify="right", no_wrap=True)
    return t


def _row(table: Table, label: str, value: str, icon: str = "") -> None:
    left = f"[{COLOR_FG_TERTIARY}]{icon} {label}[/]" if icon else f"[{COLOR_FG_TERTIARY}]{label}[/]"
    table.add_row(left, f"[{COLOR_FG_PRIMARY}]{value}[/]")


def _exp_bar(exp: int, exp_next: int, width: int = _BAR_LEN) -> str:
    """渲染玩家经验进度条。"""
    ratio = min(exp / exp_next, 1.0) if exp_next else 0
    filled = int(ratio * width)
    return (f"[{COLOR_FG_PRIMARY}]{_BAR_DONE * filled}[/]"
            f"[{COLOR_BORDER}]{_BAR_TODO * (width - filled)}[/]")


def _format_date(raw: str) -> str:
    """ISO datetime → yyyy-mm-dd"""
    return raw[:10] if len(raw) >= 10 else raw


def _make_level_table(data: dict) -> Table:
    level = data.get('level', 0)
    exp = data.get('exp', 0)
    exp_next = data.get('exp_to_next', 0)
    table = _make_table()
    if exp_next:
        table.add_row(
            "", f"[{COLOR_FG_TERTIARY}]{exp}/{exp_next}[/]")
    level_value = (
        f"[{COLOR_FG_PRIMARY}][{level}][/] {_exp_bar(exp, exp_next)}"
        if exp_next else f"[{COLOR_FG_PRIMARY}]{level}[/]"
    )
    table.add_row(
        f"[{COLOR_FG_TERTIARY}]{NF_LEVEL} 等级[/]",
        level_value,
    )
    return table


def _make_attribute_table(data: dict) -> Table:
    table = _make_table()
    _row(table, "金币", str(data.get('gold', 0)), NF_COIN)
    _row(table, "好友", str(data.get('friends_count', 0)), NF_HEART)
    created = data.get('created_at', '')
    if created:
        _row(table, "注册", _format_date(created), NF_CALENDAR)
    rank = data.get('game_rank')
    if rank and rank.get('name'):
        _row(table, "段位", rank['name'], NF_STAR)
    return table


def _make_card_content(data: dict) -> Group:
    parts = []
    title = data.get('title', '')
    if title:
        parts.extend([
            f"{ICON_INDENT}[{COLOR_FG_SECONDARY}]{title}[/]",
            "",
        ])
    parts.extend([
        _make_level_table(data),
        _make_attribute_table(data),
    ])
    return Group(*parts)


_ACTIONS_FRIEND = [
    {"label": "私聊", "cmd": "__dm__"},
    {"label": "删除好友", "cmd": "__unfriend__", "confirm": "确认删除好友 {name}?"},
]

_ACTIONS_STRANGER = [
    {"label": "添加好友", "cmd": "__addfriend__", "confirm": "确认添加 {name} 为好友?"},
    {"label": "私聊", "cmd": "__dm__"},
]

_ACTIONS_SELF = [
    {"label": "聊天样式", "cmd": "__chat_style__"},
]


class StatusPanel(Panel):
    """左侧状态面板：左右对齐的玩家名片"""

    icon_align = True

    class OpenChatStyle(Message):
        """Request the separate chat style editor."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._status_state = None
        self._viewed_name: str = ""
        self._is_other: bool = False
        self._confirming: bool = False
        self._actions: list[dict] = _ACTIONS_STRANGER
        self._friends: list[str] = []
        self._card_data: dict = {}

    def compose_content(self) -> ComposeResult:
        with VerticalScroll(classes="tab", id="t0"):
            yield Static("", classes="content", markup=True)
        with VerticalScroll(classes="tab", id="t1"):
            yield Static("", classes="content", markup=True)

    def bind_state(self, st) -> None:
        self._status_state = st.status
        st.status.add_listener(self._on_status_event)
        self._render_info()

    def reset_cursor(self) -> None:
        self._confirming = False
        super().reset_cursor()
        if self._active != 0:
            self.switch_tab(0)

    def _on_status_event(self, event: str, *args):
        del args
        if event == 'update_player_info':
            self._render_info()

    def _render_info(self) -> None:
        ss = self._status_state
        if not ss:
            return
        self.render_card(ss.player_data, is_self=True)

    def _configure_card(
        self,
        data: dict | None,
        is_self: bool,
        friends: list[str] | None,
    ) -> bool:
        is_bot = data.get('is_bot', False) if data else False
        self._card_data = data or {}
        self._is_other = not is_self and not is_bot
        self._confirming = False
        if friends is not None:
            self._friends = friends
        if self._is_other:
            self._viewed_name = data.get('name', '') if data else ''
            self._actions = (
                _ACTIONS_FRIEND
                if self._viewed_name in self._friends
                else _ACTIONS_STRANGER
            )
            self.tabs = ["信息", "操作"]
        else:
            self._viewed_name = ''
            self._actions = _ACTIONS_SELF
            self.tabs = [] if is_bot else ["信息", "操作"]
        return is_bot

    def _set_card_titles(self, name: str) -> None:
        if self._is_other:
            self.border_title = self._render_tabs()
            self.border_subtitle = name
        else:
            self.border_title = self._render_tabs() or name
            self.border_subtitle = name if self.tabs else ""

    def _render_empty_card(self) -> None:
        self.border_title = self._render_tabs() or self.border_title
        self.border_subtitle = ""
        self.query_one("#t0 .content", Static).update(
            f"{ICON_INDENT}{M_DIM}暂无数据{M_END}")

    def _render_bot_card(self, data: dict) -> None:
        title = data.get('title', '游戏机器人')
        self.query_one("#t0 .content", Static).update(
            f"{ICON_INDENT}[{COLOR_FG_SECONDARY}]{title}[/]")
        if self._active != 0:
            self.switch_tab(0)
        try:
            self.query_one("#t1").display = False
        except Exception:
            pass

    def _sync_action_tab(self) -> None:
        if self.tabs:
            self._redraw_actions()
        try:
            self.query_one("#t1").display = bool(
                self.tabs and self._active == 1)
        except Exception:
            pass

    def render_card(self, d: dict | None, is_self: bool = False,
                     friends: list[str] | None = None) -> None:
        """渲染任意玩家名片数据"""
        is_bot = self._configure_card(d, is_self, friends)
        if not d:
            self._render_empty_card()
            return

        name = d.get('name', '???')
        self._set_card_titles(name)

        if is_bot:
            self._render_bot_card(d)
            return

        self.query_one("#t0 .content", Static).update(
            _make_card_content(d))
        if self._is_other and self._active != 0:
            self.switch_tab(0)
        self._sync_action_tab()

    def _redraw_actions(self) -> None:
        """重绘操作标签页"""
        actions = self._actions
        if self._confirming:
            selected = self.selected_option
            if selected is None:
                return
            act = selected.data
            msg = act.get('confirm', '确认?').replace('{name}', self._viewed_name)
            text = self._render_confirm(msg)
            try:
                self.query_one("#t1 .content", Static).update(text)
            except Exception:
                pass
            return
        self.set_options(
            (Option(act["cmd"], act["label"], data=act) for act in actions),
            f"profile-actions:{self._viewed_name}",
        )
        try:
            self.query_one("#t1 .content", Static).update(
                self.render_options())
        except Exception:
            pass

    def _execute_action(self) -> None:
        """执行当前选中的操作"""
        selected = self.selected_option
        if selected is None:
            return
        act = selected.data
        cmd = act['cmd']
        if cmd == '__chat_style__':
            self.post_message(self.OpenChatStyle())
            return
        if not self._viewed_name:
            return
        # 需要确认的操作
        if act.get('confirm') and not self._confirming:
            self._confirming = True

            self._redraw_actions()
            return
        self._confirming = False
        if cmd == '__dm__':
            screen = self.screen
            if hasattr(screen, '_open_dm'):
                screen._open_dm(self._viewed_name)
            return
        if cmd == '__unfriend__':
            self.app.network.send({"type": "friend_remove", "name": self._viewed_name})
            return
        if cmd == '__addfriend__':
            self.app.network.send({"type": "friend_request", "name": self._viewed_name})
            return
        # 替换 {name} 并发送指令
        cmd = cmd.replace('{name}', self._viewed_name)
        self.app.send_command(cmd)

    def switch_tab(self, index: int) -> None:
        super().switch_tab(index)
        self.border_title = self._render_tabs() or self.border_title

    def reflow_content(self) -> None:
        if self._active == 1 and self.tabs:
            self._redraw_actions()

    def nav(self, action: str) -> None:
        # 操作页的导航
        if self._active == 1:
            if self._confirming:
                def _on_yes():
                    self._execute_action()
                def _on_dismiss():
                    self._confirming = False
                    self._redraw_actions()
                self._nav_confirm(action, _on_yes, _on_dismiss)
                self._redraw_actions()
                return
            if action == "up":
                if self.selection.move(-1):
                    self._redraw_actions()
                return
            elif action == "down":
                if self.selection.move(1):
                    self._redraw_actions()
                return
            elif action == "enter":
                self._execute_action()
                return
        super().nav(action)

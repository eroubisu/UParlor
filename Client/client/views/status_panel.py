"""状态面板 — 左右对齐的玩家信息展示"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static
from rich.table import Table
from rich.console import Group
from rich.rule import Rule

from ..config import (
    COLOR_FG_PRIMARY, COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    COLOR_BORDER, ICON_INDENT,
    NF_LEVEL, NF_COIN, NF_STAR, NF_HEART, NF_CALENDAR,
    M_DIM, M_END,
)
from ..widgets.panel import Panel

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
    """pip install 风格进度条"""
    ratio = min(exp / exp_next, 1.0) if exp_next else 0
    filled = int(ratio * width)
    return (f"[{COLOR_FG_PRIMARY}]{_BAR_DONE * filled}[/]"
            f"[{COLOR_BORDER}]{_BAR_TODO * (width - filled)}[/]")


def _format_date(raw: str) -> str:
    """ISO datetime → yyyy-mm-dd"""
    return raw[:10] if len(raw) >= 10 else raw


_ACTIONS_FRIEND = [
    {"label": "私聊", "cmd": "__dm__"},
    {"label": "删除好友", "cmd": "__unfriend__", "confirm": "确认删除好友 {name}?"},
]

_ACTIONS_STRANGER = [
    {"label": "添加好友", "cmd": "__addfriend__", "confirm": "确认添加 {name} 为好友?"},
    {"label": "私聊", "cmd": "__dm__"},
]


class StatusPanel(Panel):
    """左侧状态面板：左右对齐的玩家名片"""

    icon_align = True

    def __init__(self, **kw):
        super().__init__(**kw)
        self._status_state = None
        self._viewed_name: str = ""
        self._is_other: bool = False
        self._action_cursor: int = 0
        self._confirming: bool = False
        self._actions: list[dict] = _ACTIONS_STRANGER
        self._friends: list[str] = []

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
        self._action_cursor = 0
        self._confirming = False
        super().reset_cursor()
        if self._active != 0:
            self.switch_tab(0)

    def _on_status_event(self, event: str, *args):
        if event == 'update_player_info':
            self._render_info()

    def _render_info(self) -> None:
        ss = self._status_state
        if not ss:
            return
        self.render_card(ss.player_data, is_self=True)

    def render_card(self, d: dict | None, is_self: bool = False,
                     friends: list[str] | None = None) -> None:
        """渲染任意玩家名片数据"""
        is_bot = d.get('is_bot', False) if d else False
        self._is_other = not is_self and not is_bot
        self._confirming = False
        self._confirm_cursor = 0
        if friends is not None:
            self._friends = friends
        if self._is_other:
            self._viewed_name = d.get('name', '') if d else ''
            self._actions = (_ACTIONS_FRIEND
                            if self._viewed_name in self._friends
                            else _ACTIONS_STRANGER)
            self.tabs = ["信息", "操作"]
            self._action_cursor = 0
        else:
            self._viewed_name = ''
            self._actions = _ACTIONS_STRANGER
            self.tabs = []
        if not d:
            self.border_title = self._render_tabs() or self.border_title
            self.border_subtitle = ""
            self.query_one("#t0 .content", Static).update(
                f"{ICON_INDENT}{M_DIM}暂无数据{M_END}")
            return

        # ── 头部 ──
        name = d.get('name', '???')
        if self._is_other:
            # 查看他人：标签页在 border_title，名字在 border_subtitle
            self.border_title = self._render_tabs()
            self.border_subtitle = name
        else:
            # 查看自己/机器人：无标签，名字在 border_title
            self.border_title = name
            self.border_subtitle = ""

        # ── 机器人：只显示简介 ──
        if is_bot:
            title = d.get('title', '游戏机器人')
            self.query_one("#t0 .content", Static).update(
                f"{ICON_INDENT}[{COLOR_FG_SECONDARY}]{title}[/]")
            if self._active != 0:
                self.switch_tab(0)
            try:
                self.query_one("#t1").display = False
            except Exception:
                pass
            return

        title = d.get('title', '')
        header = ""
        if title:
            header = f"{ICON_INDENT}[{COLOR_FG_SECONDARY}]{title}[/]"

        # ── 等级区：上行 exp 数字右对齐，下行 左等级 右[level]进度条 ──
        level = d.get('level', 0)
        exp = d.get('exp', 0)
        exp_next = d.get('exp_to_next', 0)

        lvl_table = _make_table()
        if exp_next:
            lvl_table.add_row("", f"[{COLOR_FG_TERTIARY}]{exp}/{exp_next}[/]")
        bar_right = f"[{COLOR_FG_PRIMARY}][{level}][/] {_exp_bar(exp, exp_next)}" if exp_next else f"[{COLOR_FG_PRIMARY}]{level}[/]"
        lvl_table.add_row(
            f"[{COLOR_FG_TERTIARY}]{NF_LEVEL} 等级[/]",
            bar_right,
        )

        # ── 属性表 ──
        t = _make_table()
        _row(t, "金币", str(d.get('gold', 0)), NF_COIN)
        _row(t, "好友", str(d.get('friends_count', 0)), NF_HEART)

        created = d.get('created_at', '')
        if created:
            _row(t, "注册", _format_date(created), NF_CALENDAR)

        rank = d.get('game_rank')
        if rank and rank.get('name'):
            _row(t, "段位", rank['name'], NF_STAR)

        parts = []
        if header:
            parts += [header, Rule(style=COLOR_BORDER)]
        parts += [lvl_table, t]
        self.query_one("#t0 .content", Static).update(Group(*parts))
        # 切到信息页
        if self._active != 0:
            self.switch_tab(0)
        # 刷新操作页
        if self._is_other:
            self._redraw_actions()
        # 隐藏 t1 tab when viewing self
        try:
            self.query_one("#t1").display = self._is_other and self._active == 1
        except Exception:
            pass

    def _redraw_actions(self) -> None:
        """重绘操作标签页"""
        actions = self._actions
        if self._confirming:
            act = actions[self._action_cursor]
            msg = act.get('confirm', '确认?').replace('{name}', self._viewed_name)
            text = self._render_confirm(msg)
            try:
                self.query_one("#t1 .content", Static).update(text)
            except Exception:
                pass
            return
        lines = []
        for i, act in enumerate(actions):
            sel = i == self._action_cursor
            label = act['label']
            if sel:
                lines.append(f"[bold {COLOR_FG_PRIMARY}]> {label}[/]")
            else:
                lines.append(f"[{COLOR_FG_TERTIARY}]{ICON_INDENT}{label}[/]")
        try:
            self.query_one("#t1 .content", Static).update("\n".join(lines))
        except Exception:
            pass

    def _execute_action(self) -> None:
        """执行当前选中的操作"""
        if not self._viewed_name:
            return
        actions = self._actions
        act = actions[self._action_cursor]
        cmd = act['cmd']
        # 需要确认的操作
        if act.get('confirm') and not self._confirming:
            self._confirming = True
            self._confirm_cursor = 0
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

    def nav(self, action: str) -> None:
        # 操作页的导航
        if self._is_other and self._active == 1:
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
                if self._action_cursor > 0:
                    self._action_cursor -= 1
                    self._redraw_actions()
                return
            elif action == "down":
                if self._action_cursor < len(self._actions) - 1:
                    self._action_cursor += 1
                    self._redraw_actions()
                return
            elif action == "enter":
                self._execute_action()
                return
        super().nav(action)

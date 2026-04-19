"""在线玩家列表面板 — 好友/在线/全部 三标签 + 搜索 + 光标"""

from __future__ import annotations

from textual.widgets import Input

from ..config import (
    COLOR_FG_PRIMARY, COLOR_HINT_TAB_DIM, ICON_INDENT,
    NF_ONLINE, NF_OFFLINE, COLOR_ONLINE, COLOR_OFFLINE,
    M_DIM, M_END,
)
from ..widgets.panel import Panel, PlayerSelected

_TABS = ["好友", "在线", "全部"]


class OnlineListPanel(Panel):
    """左侧玩家列表：三标签 + 搜索 + 光标导航"""

    icon_align = True
    follow_focus = True
    tabs = list(_TABS)
    has_input = True
    placeholder = "搜索玩家……"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._online_state = None
        self._search: str = ""
        self._online_names: set[str] = set()

    def bind_state(self, st) -> None:
        self._online_state = st.online
        self._online_names = {u['name'] for u in st.online.users}
        st.online.add_listener(self._on_event)
        self._render_list()

    def _on_event(self, event: str, *args):
        if event in ('update_users', 'update_friends', 'update_all_users'):
            self._online_names = {u['name'] for u in self._online_state.users}
            self._render_list()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._search = event.value.strip().lower()
        self._cursor = 0
        self._render_list()
        self._emit_selected()
        event.stop()

    def _get_items(self) -> list[str]:
        """根据当前标签返回名字列表"""
        st = self._online_state
        if not st:
            return []
        tab = _TABS[self._active]
        if tab == "好友":
            names = list(st.friends or [])
        elif tab == "在线":
            names = [u['name'] for u in st.users]
        else:
            names = list(st.all_users)
        if self._search:
            names = [n for n in names if self._search in n.lower()]
        return names

    def _render_list(self) -> None:
        items = self._get_items()
        lines: list[str] = []
        if not items:
            lines.append(f"{ICON_INDENT}{M_DIM}"
                         f"{'无匹配玩家' if self._search else '暂无玩家'}{M_END}")
        else:
            self._cursor = min(self._cursor, len(items) - 1)
            is_friend_tab = _TABS[self._active] == "好友"
            for i, name in enumerate(items):
                # 好友标签下显示在线/离线状态图标
                if is_friend_tab:
                    online = name in self._online_names
                    dot = (f"[{COLOR_ONLINE}]{NF_ONLINE}[/]" if online
                           else f"[{COLOR_OFFLINE}]{NF_OFFLINE}[/]")
                    if i == self._cursor:
                        lines.append(
                            f"{dot} [bold {COLOR_FG_PRIMARY}]{name}[/]")
                    else:
                        lines.append(
                            f"{dot} [{COLOR_HINT_TAB_DIM}]{name}[/]")
                else:
                    if i == self._cursor:
                        lines.append(
                            f"[bold {COLOR_FG_PRIMARY}]> {name}[/]")
                    else:
                        lines.append(
                            f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{name}[/]")
        self._focus_line = self._cursor
        self.update("\n".join(lines))

    def _emit_selected(self) -> None:
        items = self._get_items()
        if items and 0 <= self._cursor < len(items):
            self.post_message(PlayerSelected(items[self._cursor]))

    def switch_tab(self, index: int) -> None:
        super().switch_tab(index)
        self._cursor = 0
        self._render_list()
        self._emit_selected()

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._search = ""
        self._render_list()

    # ── 导航 ──

    def nav(self, action: str) -> None:
        if action in ("tab_prev", "tab_next"):
            super().nav(action)
            return
        items = self._get_items()
        def _after():
            self._render_list()
            self._emit_selected()
        if not self._cursor_nav(
            action, len(items),
            on_enter=self._emit_selected,
            redraw=_after,
        ):
            super().nav(action)

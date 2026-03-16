"""OnlineUsersPanel — 好友/所有用户/在线用户/搜索 标签面板"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.widgets import RichLog, Static
from textual.widget import Widget

from ...config import (
    MAX_LINES_ONLINE,
    M_DIM, M_END,
    COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    COLOR_ACCENT,
    COLOR_HINT_TAB_ACTIVE, COLOR_HINT_TAB_DIM,
)
from ...state import ModuleStateManager
from ...widgets.helpers import build_tab_overflow
from ...widgets.input_bar import InputBar


_TABS = ["friends", "all", "online", "search"]
_TAB_LABELS = {"friends": "好友", "all": "所有", "online": "在线", "search": "搜索"}


class OnlineUsersPanel(Widget):
    """在线用户列表面板 — 四标签页：好友/所有/在线/搜索"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._tab: str = "friends"
        self._cursor: int = 0
        self._wants_insert: bool = False
        self._search_query: str = ""
        self._state_mgr: ModuleStateManager | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="online-header", markup=True)
        yield RichLog(
            id="online-log", wrap=True, highlight=True,
            markup=True, max_lines=MAX_LINES_ONLINE, min_width=0,
        )
        yield InputBar(prompt_id="online-prompt", id="online-input-bar")

    def on_mount(self) -> None:
        try:
            self.query_one("#online-input-bar", InputBar).remove_class("visible")
        except Exception:
            pass

    # ── InputBar 标准接口 ──

    def show_prompt(self, text: str = ""):
        try:
            self.query_one("#online-input-bar", InputBar).show_prompt(text)
        except Exception:
            pass

    def update_prompt(self, text: str):
        try:
            self.query_one("#online-input-bar", InputBar).update_prompt(text)
        except Exception:
            pass

    def hide_prompt(self):
        try:
            self.query_one("#online-input-bar", InputBar).hide_prompt()
        except Exception:
            pass

    def show_input_bar(self):
        try:
            self.query_one("#online-input-bar", InputBar).add_class("visible")
        except Exception:
            pass
        try:
            log = self.query_one("#online-log", RichLog)
            log.scroll_end(animate=False)
        except Exception:
            pass

    def hide_input_bar(self):
        try:
            self.query_one("#online-input-bar", InputBar).remove_class("visible")
        except Exception:
            pass

    def cancel_input(self):
        self._wants_insert = False

    @property
    def wants_insert(self) -> bool:
        return self._wants_insert

    # ── 导航协议 ──

    def nav_down(self):
        items = self._current_items()
        if items:
            self._cursor = (self._cursor + 1) % len(items)
            self._render_list()

    def nav_up(self):
        items = self._current_items()
        if items:
            self._cursor = (self._cursor - 1) % len(items)
            self._render_list()

    def nav_enter(self):
        if self._tab == "search" and not self._wants_insert:
            self._wants_insert = True
            self.show_input_bar()
            return
        items = self._current_items()
        if not items:
            return
        if self._cursor >= len(items):
            return
        name = items[self._cursor]
        st = self._state_mgr
        if not st:
            return
        if name in st.online.friends:
            self.app.network.send({"type": "friend_remove", "name": name})
        else:
            self.app.network.send({"type": "friend_add", "name": name})

    def nav_back(self) -> bool:
        if self._wants_insert:
            return False
        if self._tab != "friends":
            self._tab = "friends"
            self._cursor = 0
            self._render_all()
            return True
        return False

    def nav_escape(self) -> bool:
        if self._wants_insert:
            self._wants_insert = False
            self.hide_input_bar()
            return True
        return False

    def nav_tab_next(self):
        if self._wants_insert:
            return
        idx = _TABS.index(self._tab) if self._tab in _TABS else 0
        self._tab = _TABS[(idx + 1) % len(_TABS)]
        self._cursor = 0
        self._render_all()

    def nav_tab_prev(self):
        if self._wants_insert:
            return
        idx = _TABS.index(self._tab) if self._tab in _TABS else 0
        self._tab = _TABS[(idx - 1) % len(_TABS)]
        self._cursor = 0
        self._render_all()

    # ── 搜索输入 ──

    def on_search_change(self, text: str):
        """实时搜索过滤 — 由 Screen 的 on_text_area_changed 调用"""
        self._search_query = text.strip().lower()
        self._cursor = 0
        self._render_list()

    def on_input_submit(self, text: str):
        """提交搜索 — Enter 后退出 INSERT 但保持结果"""
        self._search_query = text.strip().lower()
        self._cursor = 0
        self._wants_insert = False
        self.hide_input_bar()
        self._render_list()

    # ── 数据 ──

    def _current_items(self) -> list[str]:
        st = self._state_mgr
        if not st:
            return []
        if self._tab == "friends":
            return list(st.online.friends)
        elif self._tab == "all":
            return list(st.online.all_users)
        elif self._tab == "online":
            return [u["name"] if isinstance(u, dict) else str(u)
                    for u in st.online.users]
        elif self._tab == "search":
            q = self._search_query
            if not q:
                return list(st.online.all_users)
            return [n for n in st.online.all_users if q in n.lower()]
        return []

    # ── 渲染 ──

    def _render_all(self):
        self._render_header()
        self._render_list()

    def _render_header(self):
        tab_parts = []
        for t in _TABS:
            label = _TAB_LABELS[t]
            if t == self._tab:
                plain = f"● {label}"
                markup = f"[{COLOR_HINT_TAB_ACTIVE}]{plain}[/]"
            else:
                plain = f"  {label}"
                markup = f"  [{COLOR_HINT_TAB_DIM}]{label}[/]"
            tab_parts.append((markup, cell_len(plain)))

        try:
            avail = self.query_one("#online-header", Static).size.width
        except Exception:
            avail = 40
        if avail <= 0:
            avail = 40

        active_idx = _TABS.index(self._tab) if self._tab in _TABS else 0
        tab_line = build_tab_overflow(tab_parts, active_idx, avail, COLOR_FG_TERTIARY)

        try:
            header = self.query_one("#online-header", Static)
            header.update(tab_line)
        except Exception:
            pass

    def _render_list(self):
        try:
            log: RichLog = self.query_one("#online-log", RichLog)
        except Exception:
            return

        log.clear()
        items = self._current_items()
        st = self._state_mgr
        friends = set(st.online.friends) if st else set()
        online_names = set()
        if st:
            for u in st.online.users:
                if isinstance(u, dict):
                    online_names.add(u.get("name", ""))
                else:
                    online_names.add(str(u))

        if not items:
            if self._tab == "search" and self._search_query:
                log.write(RichText.from_markup(
                    f"{M_DIM}无匹配用户{M_END}"))
            elif self._tab == "friends":
                log.write(RichText.from_markup(
                    f"{M_DIM}暂无好友{M_END}"))
            else:
                log.write(RichText.from_markup(
                    f"{M_DIM}暂无用户{M_END}"))
            return

        if self._cursor >= len(items):
            self._cursor = len(items) - 1

        for i, name in enumerate(items):
            is_friend = name in friends
            is_online = name in online_names
            sel = i == self._cursor

            markers = []
            if is_online:
                markers.append("在线")
            if is_friend and self._tab != "friends":
                markers.append("好友")
            suffix = f" [{COLOR_FG_TERTIARY}]({', '.join(markers)}){M_END}" if markers else ""

            if sel:
                line = f" [{COLOR_ACCENT}]●[/] [b]{name}[/b]{suffix}"
            else:
                line = f"   [{COLOR_FG_SECONDARY}]{name}{M_END}{suffix}"

            log.write(RichText.from_markup(line))

        log.write(RichText.from_markup(""))
        if self._tab == "search":
            hint = f"[{COLOR_FG_TERTIARY}]Enter 搜索  j/k 导航  h/l 切换{M_END}"
        else:
            hint = f"[{COLOR_FG_TERTIARY}]j/k 导航  Enter 添加/移除好友  h/l 切换{M_END}"
        log.write(RichText.from_markup(hint))

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event in ('update_users', 'update_friends', 'update_all_users'):
            self._render_all()

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        state.online.set_listener(self._on_state_event)
        self._render_all()

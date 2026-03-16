"""OnlineUsersPanel — 好友/所有用户/在线用户/搜索 标签面板

状态机:
  LIST     — j/k 移动用户光标，Enter 打开操作菜单
  ACTION   — j/k 在操作项间移动，Enter 执行
  CONFIRM  — 确认添加/删除好友
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.widgets import RichLog, Static
from textual.widget import Widget

from ..config import (
    MAX_LINES_ONLINE,
    M_DIM, M_END,
    COLOR_FG_PRIMARY, COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    COLOR_ACCENT,
    COLOR_HINT_TAB_ACTIVE, COLOR_HINT_TAB_DIM,
)
from ..state import ModuleStateManager
from ..widgets import _set_pane_subtitle
from ..widgets.helpers import build_tab_overflow, _widget_width
from ..widgets.input_bar import InputBar


_TABS = ["friends", "all", "online", "search"]
_TAB_LABELS = {"friends": "好友", "all": "所有", "online": "在线", "search": "搜索"}

_MODE_LIST = 'list'
_MODE_ACTION = 'action'
_MODE_CONFIRM = 'confirm'
_MODE_GIFT = 'gift'


class OnlineUsersPanel(Widget):
    """在线用户列表面板 — 四标签页 + 操作菜单"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._tab: str = "friends"
        self._cursor: int = 0
        self._mode: str = _MODE_LIST
        self._action_cursor: int = 0
        self._confirm_label: str = ""
        self._confirm_action: str = ""  # 'friend_request' | 'friend_remove'
        self._confirm_target: str = ""
        self._gift_cursor: int = 0
        self._gift_target: str = ""
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

    # ── 操作菜单 ──

    def _is_self(self, name: str) -> bool:
        """检测是否选中了自己"""
        st = self._state_mgr
        if not st:
            return False
        my_name = st.chat._my_name
        return name == my_name

    def _actions_for_user(self, name: str) -> list[tuple[str, str]]:
        """根据用户关系返回操作列表 [(action_id, label), ...]"""
        st = self._state_mgr
        if not st:
            return []
        is_friend = name in st.online.friends
        actions = []
        actions.append(('private_chat', '发起私聊'))
        if is_friend:
            actions.append(('gift', '赠送礼物'))
            actions.append(('friend_remove', '删除好友'))
        else:
            actions.append(('friend_request', '申请好友'))
        return actions

    def _get_gift_items(self) -> list[dict]:
        """获取可赠送的物品"""
        st = self._state_mgr
        if not st:
            return []
        return [item for item in st.inventory.items if item.get('count', 0) > 0]

    # ── 导航协议 ──

    def nav_down(self):
        if self._mode == _MODE_LIST:
            items = self._current_items()
            if items:
                self._cursor = (self._cursor + 1) % len(items)
        elif self._mode == _MODE_ACTION:
            items = self._current_items()
            if items and self._cursor < len(items):
                actions = self._actions_for_user(items[self._cursor])
                if actions:
                    self._action_cursor = (self._action_cursor + 1) % len(actions)
        elif self._mode == _MODE_GIFT:
            gift_items = self._get_gift_items()
            if gift_items:
                self._gift_cursor = (self._gift_cursor + 1) % len(gift_items)
        self._render_list()

    def nav_up(self):
        if self._mode == _MODE_LIST:
            items = self._current_items()
            if items:
                self._cursor = (self._cursor - 1) % len(items)
        elif self._mode == _MODE_ACTION:
            items = self._current_items()
            if items and self._cursor < len(items):
                actions = self._actions_for_user(items[self._cursor])
                if actions:
                    self._action_cursor = (self._action_cursor - 1) % len(actions)
        elif self._mode == _MODE_GIFT:
            gift_items = self._get_gift_items()
            if gift_items:
                self._gift_cursor = (self._gift_cursor - 1) % len(gift_items)
        self._render_list()

    def nav_enter(self):
        items = self._current_items()
        if not items:
            return
        if self._cursor >= len(items):
            return

        if self._mode == _MODE_LIST:
            name = items[self._cursor]
            if self._is_self(name):
                return
            self._action_cursor = 0
            self._mode = _MODE_ACTION
            self._render_list()
            return

        if self._mode == _MODE_ACTION:
            name = items[self._cursor]
            actions = self._actions_for_user(name)
            if not actions:
                return
            action_id, label = actions[self._action_cursor]
            if action_id == 'private_chat':
                st = self._state_mgr
                if st:
                    st.chat.open_private_tab(name)
                self._mode = _MODE_LIST
                self._render_list()
                return
            if action_id == 'gift':
                self._gift_target = name
                self._gift_cursor = 0
                self._mode = _MODE_GIFT
                self._render_list()
                return
            # friend_request / friend_remove → 进入确认
            if action_id == 'friend_request':
                self._confirm_label = f"确定向 {name} 发送好友申请？"
            else:
                self._confirm_label = f"确定删除好友 {name}？"
            self._confirm_action = action_id
            self._confirm_target = name
            self._mode = _MODE_CONFIRM
            self._render_list()
            return

        if self._mode == _MODE_GIFT:
            gift_items = self._get_gift_items()
            if not gift_items:
                self._mode = _MODE_ACTION
                self._render_list()
                return
            item = gift_items[self._gift_cursor]
            # 执行赠送
            try:
                self.app.send_command(f"/gift {item['id']}")
                self.app.send_command(self._gift_target)
            except Exception:
                pass
            self._mode = _MODE_LIST
            self._render_list()
            return

        if self._mode == _MODE_CONFIRM:
            if self._confirm_action == 'friend_request':
                self.app.network.send({"type": "friend_request", "name": self._confirm_target})
            elif self._confirm_action == 'friend_remove':
                self.app.network.send({"type": "friend_remove", "name": self._confirm_target})
            self._mode = _MODE_LIST
            self._render_list()
            return

    def nav_back(self) -> bool:
        if self._wants_insert:
            return False
        if self._mode == _MODE_CONFIRM:
            self._mode = _MODE_ACTION
            self._render_list()
            return True
        if self._mode == _MODE_GIFT:
            self._mode = _MODE_ACTION
            self._render_list()
            return True
        if self._mode == _MODE_ACTION:
            self._mode = _MODE_LIST
            self._render_list()
            return True
        if self._tab != "friends":
            self._tab = "friends"
            self._cursor = 0
            self._mode = _MODE_LIST
            self._render_all()
            return True
        return False

    def nav_escape(self) -> bool:
        if self._wants_insert:
            self._wants_insert = False
            self.hide_input_bar()
            return True
        if self._mode != _MODE_LIST:
            self._mode = _MODE_LIST
            self._render_list()
            return True
        return False

    def nav_tab_next(self):
        if self._wants_insert:
            return
        idx = _TABS.index(self._tab) if self._tab in _TABS else 0
        self._tab = _TABS[(idx + 1) % len(_TABS)]
        self._cursor = 0
        self._mode = _MODE_LIST
        self._render_all()

    def nav_tab_prev(self):
        if self._wants_insert:
            return
        idx = _TABS.index(self._tab) if self._tab in _TABS else 0
        self._tab = _TABS[(idx - 1) % len(_TABS)]
        self._cursor = 0
        self._mode = _MODE_LIST
        self._render_all()

    # ── 搜索输入 ──

    def on_search_change(self, text: str):
        self._search_query = text.strip().lower()
        self._cursor = 0
        self._render_list()

    def on_input_submit(self, text: str):
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
                return []
            return [n for n in st.online.all_users if q in n.lower()]
        return []

    def _online_names(self) -> set[str]:
        st = self._state_mgr
        if not st:
            return set()
        names = set()
        for u in st.online.users:
            if isinstance(u, dict):
                names.add(u.get("name", ""))
            else:
                names.add(str(u))
        return names

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

        active_idx = _TABS.index(self._tab) if self._tab in _TABS else 0
        avail = _widget_width(self, "online-header")
        tab_line = build_tab_overflow(tab_parts, active_idx, avail, COLOR_FG_TERTIARY)

        try:
            header = self.query_one("#online-header", Static)
            header.update(tab_line)
        except Exception:
            pass

    def on_resize(self, event) -> None:
        self._render_header()

    def _render_list(self):
        try:
            log: RichLog = self.query_one("#online-log", RichLog)
        except Exception:
            return

        log.clear()
        items = self._current_items()
        st = self._state_mgr
        friends = set(st.online.friends) if st else set()
        online_names = self._online_names()

        if not items:
            if self._tab == "search" and self._search_query:
                log.write(RichText.from_markup(
                    f"{M_DIM}无匹配用户{M_END}"))
            elif self._tab == "friends":
                log.write(RichText.from_markup(
                    f"{M_DIM}还没有好友{M_END}"))
            else:
                log.write(RichText.from_markup(
                    f"{M_DIM}(空){M_END}"))
            return

        if self._cursor >= len(items):
            self._cursor = len(items) - 1

        for i, name in enumerate(items):
            is_friend = name in friends
            is_online = name in online_names
            sel = i == self._cursor

            # 右侧状态标记
            markers = []
            if is_online:
                markers.append("在线")
            if is_friend and self._tab != "friends":
                markers.append("好友")
            suffix = f"  [{COLOR_FG_TERTIARY}]{', '.join(markers)}{M_END}" if markers else ""

            if sel:
                line = f" [{COLOR_ACCENT}]●[/] [bold {COLOR_FG_PRIMARY}]{name}[/]{suffix}"
            else:
                line = f"   [{COLOR_FG_SECONDARY}]{name}[/]{suffix}"
            log.write(RichText.from_markup(line))

            # 选中项下方展开子内容
            if not sel:
                continue

            if self._mode == _MODE_ACTION:
                actions = self._actions_for_user(name)
                for ai, (_, label) in enumerate(actions):
                    if ai == self._action_cursor:
                        log.write(RichText.from_markup(
                            f"     [{COLOR_ACCENT}]●[/] [bold {COLOR_FG_PRIMARY}]{label}[/]"))
                    else:
                        log.write(RichText.from_markup(
                            f"       [{COLOR_FG_SECONDARY}]{label}[/]"))

            elif self._mode == _MODE_GIFT:
                gift_items = self._get_gift_items()
                if not gift_items:
                    log.write(RichText.from_markup(
                        f"     {M_DIM}没有可赠送的物品{M_END}"))
                else:
                    for gi, gitem in enumerate(gift_items):
                        gname = gitem.get('name', gitem.get('id', '?'))
                        gcount = gitem.get('count', 0)
                        if gi == self._gift_cursor:
                            log.write(RichText.from_markup(
                                f"     [{COLOR_ACCENT}]●[/] [bold {COLOR_FG_PRIMARY}]{gname}[/] [{COLOR_FG_TERTIARY}]x{gcount}[/]"))
                        else:
                            log.write(RichText.from_markup(
                                f"       [{COLOR_FG_SECONDARY}]{gname}[/] [{COLOR_FG_TERTIARY}]x{gcount}[/]"))

            elif self._mode == _MODE_CONFIRM:
                log.write(RichText.from_markup(
                    f"     [{COLOR_FG_SECONDARY}]{self._confirm_label}[/]"))

        # 更新面板副标题显示在线人数
        online_count = len(online_names)
        if online_count:
            _set_pane_subtitle(self, f"在线({online_count})")
        else:
            _set_pane_subtitle(self, "")

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event in ('update_users', 'update_friends', 'update_all_users'):
            # 数据变更时重置到列表模式
            if self._mode != _MODE_LIST:
                self._mode = _MODE_LIST
            self._render_all()

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        state.online.set_listener(self._on_state_event)
        self._render_all()

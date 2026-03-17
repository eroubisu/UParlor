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
)
from ..state import ModuleStateManager
from ..widgets import _set_pane_subtitle
from ..widgets.helpers import render_tab_header, _widget_width
from ..widgets.input_bar import InputBar
from ..widgets.prompt import InputBarMixin
from ._card_render import render_card


_TABS = ["friends", "all", "online", "search"]
_TAB_LABELS = {"friends": "好友", "all": "所有", "online": "在线", "search": "搜索"}

_MODE_LIST = 'list'
_MODE_ACTION = 'action'
_MODE_CONFIRM = 'confirm'
_MODE_CARD = 'card'


def _truncate_name(name: str, max_width: int) -> str:
    """将名字截断到 max_width 显示列内，溢出时末尾加 ~"""
    if max_width < 1:
        return "~"
    w = 0
    for i, ch in enumerate(name):
        cw = cell_len(ch)
        if w + cw > max_width:
            # 回退一格放 ~
            if w > 0:
                return name[:i] + "~" if w + 1 <= max_width + 1 else name[:i]
            return "~"
        w += cw
    return name


class OnlineUsersPanel(InputBarMixin, Widget):
    """在线用户列表面板 — 四标签页 + 操作菜单"""

    _input_bar_id = "online-input-bar"
    _scroll_target_id = "online-log"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._tab: str = "friends"
        self._cursor: int = 0
        self._mode: str = _MODE_LIST
        self._action_cursor: int = 0
        self._confirm_label: str = ""
        self._confirm_action: str = ""  # 'friend_request' | 'friend_remove'
        self._confirm_target: str = ""
        self._scroll_offset: int = 0
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
        actions.append(('view_card', '查看名片'))
        if is_friend:
            actions.append(('private_chat', '发起私聊'))
        if is_friend:
            actions.append(('friend_remove', '删除好友'))
        else:
            actions.append(('friend_request', '申请好友'))
        return actions

    # ── 导航协议 ──

    def _visible_height(self) -> int:
        """RichLog 可见行数"""
        try:
            log = self.query_one("#online-log", RichLog)
            h = log.scrollable_content_region.height
            return h if h > 0 else 10
        except Exception:
            return 10

    def _ensure_scroll(self):
        items = self._current_items()
        if not items:
            return
        vh = self._visible_height()
        # 计算光标行需要的额外展开行数
        extra = 0
        if self._mode == _MODE_ACTION:
            extra = len(self._actions_for_user(items[self._cursor])) if self._cursor < len(items) else 0
        elif self._mode == _MODE_CONFIRM:
            extra = 1
        # 保证光标及展开内容在视口内
        need = 1 + extra
        if self._cursor < self._scroll_offset:
            self._scroll_offset = self._cursor
        elif self._cursor + need > self._scroll_offset + vh:
            self._scroll_offset = self._cursor + need - vh
        self._scroll_offset = max(0, self._scroll_offset)

    def nav_down(self):
        if self._mode == _MODE_CARD:
            return
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
        self._ensure_scroll()
        self._render_list()

    def nav_up(self):
        if self._mode == _MODE_CARD:
            return
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
        self._ensure_scroll()
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
            if action_id == 'view_card':
                try:
                    self.app.network.send({
                        'type': 'get_profile_card',
                        'target': name,
                    })
                except Exception:
                    pass
                self._mode = _MODE_CARD
                self._render_card_waiting()
                return
            if action_id == 'private_chat':
                st = self._state_mgr
                if st:
                    st.chat.open_private_tab(name)
                self._mode = _MODE_LIST
                self._render_list()
                return
            # friend_request / friend_remove → 进入确认
            if action_id == 'friend_request':
                self._confirm_label = f"确认向 {name} 发送好友申请？"
            else:
                self._confirm_label = f"确认删除好友 {name}？"
            self._confirm_action = action_id
            self._confirm_target = name
            self._mode = _MODE_CONFIRM
            self._render_list()
            return

        if self._mode == _MODE_CONFIRM:
            if self._confirm_action == 'friend_request':
                self.app.network.send({"type": "friend_request", "name": self._confirm_target})
            elif self._confirm_action == 'friend_remove':
                self.app.network.send({"type": "friend_remove", "name": self._confirm_target})
                st = self._state_mgr
                if st:
                    st.chat.close_private_tab(self._confirm_target)
            self._mode = _MODE_LIST
            self._render_list()
            return

    def nav_back(self) -> bool:
        if self._wants_insert:
            return False
        if self._mode == _MODE_CARD:
            self._mode = _MODE_LIST
            self._render_list()
            return True
        if self._mode == _MODE_CONFIRM:
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
            self._scroll_offset = 0
            self._mode = _MODE_LIST
            self._render_all()
            return True
        return False

    def nav_escape(self) -> bool:
        if self._wants_insert:
            self._wants_insert = False
            self.hide_input_bar()
            return True
        if self._mode == _MODE_CARD:
            self._mode = _MODE_LIST
            self._render_list()
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
        self._scroll_offset = 0
        self._mode = _MODE_LIST
        self._render_all()

    def nav_tab_prev(self):
        if self._wants_insert:
            return
        idx = _TABS.index(self._tab) if self._tab in _TABS else 0
        self._tab = _TABS[(idx - 1) % len(_TABS)]
        self._cursor = 0
        self._scroll_offset = 0
        self._mode = _MODE_LIST
        self._render_all()

    # ── 搜索输入 ──

    def on_search_change(self, text: str):
        self._search_query = text.strip().lower()
        self._cursor = 0
        self._scroll_offset = 0
        self._render_list()

    def on_input_submit(self, text: str):
        self._search_query = text.strip().lower()
        self._cursor = 0
        self._scroll_offset = 0
        self._wants_insert = False
        self.hide_input_bar()
        self._render_list()

    # ── 数据 ──

    def _current_items(self) -> list[str]:
        st = self._state_mgr
        if not st:
            return []
        my_name = st.chat._my_name
        if self._tab == "friends":
            return [n for n in st.online.friends if n != my_name]
        elif self._tab == "all":
            return [n for n in st.online.all_users if n != my_name]
        elif self._tab == "online":
            return [u["name"] if isinstance(u, dict) else str(u)
                    for u in st.online.users
                    if (u.get("name") if isinstance(u, dict) else str(u)) != my_name]
        elif self._tab == "search":
            q = self._search_query
            if not q:
                return []
            return [n for n in st.online.all_users if q in n.lower() and n != my_name]
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
        self._update_subtitle()

    def _render_header(self):
        render_tab_header(self, "online-header", _TABS, _TAB_LABELS, self._tab)

    def on_resize(self, event) -> None:
        self._render_all()

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
                    f"{M_DIM}暂无好友{M_END}"))
            else:
                log.write(RichText.from_markup(
                    f"{M_DIM}暂无用户{M_END}"))
            self._update_subtitle()
            return

        if self._cursor >= len(items):
            self._cursor = len(items) - 1

        self._ensure_scroll()
        avail = _widget_width(self, "online-log")
        vh = self._visible_height()
        end = min(len(items), self._scroll_offset + vh + 5)  # 多渲染几行留余量
        start = self._scroll_offset

        need_sb = len(items) > vh

        for i in range(start, end):
            name = items[i]
            is_friend = name in friends
            is_online = name in online_names
            sel = i == self._cursor

            line = self._format_user_line(
                name, is_online, is_friend, sel, avail, need_sb)
            log.write(RichText.from_markup(line))

            # 选中项下方展开子内容
            if not sel:
                continue

            if self._mode == _MODE_ACTION:
                actions = self._actions_for_user(name)
                for ai, (_, label) in enumerate(actions):
                    if ai == self._action_cursor:
                        log.write(RichText.from_markup(
                            f"     [{COLOR_ACCENT}]\u25cf[/] [bold {COLOR_FG_PRIMARY}]{label}[/]"))
                    else:
                        log.write(RichText.from_markup(
                            f"       [{COLOR_FG_SECONDARY}]{label}[/]"))

            elif self._mode == _MODE_CONFIRM:
                log.write(RichText.from_markup(
                    f"     [{COLOR_FG_SECONDARY}]{self._confirm_label}[/]"))

        self._update_subtitle()

    def _update_subtitle(self):
        """始终更新面板副标题为在线人数"""
        online_count = len(self._online_names())
        if online_count:
            _set_pane_subtitle(self, f"在线({online_count})")
        else:
            _set_pane_subtitle(self, "")



    def _format_user_line(self, name, is_online, is_friend, selected, avail, need_sb=False):
        """格式化用户行：名字左对齐，状态右对齐，名字可截断

        好友面板：仅显示在线状态 ■/□
        在线面板：仅显示好友状态 ■/□
        其他面板：双方块 左=好友 右=在线
        """
        if self._tab == "friends":
            # 好友面板：仅显示在线状态
            char = '■' if is_online else '□'
            color = COLOR_ACCENT if is_online else COLOR_FG_TERTIARY
            status_markup = f"[{color}]{char}[/]"
            status_plain_w = 1
        elif self._tab == "online":
            # 在线面板：仅显示好友状态
            char = '■' if is_friend else '□'
            color = COLOR_ACCENT if is_friend else COLOR_FG_TERTIARY
            status_markup = f"[{color}]{char}[/]"
            status_plain_w = 1
        else:
            # all / search：双方块
            friend_char = '■' if is_friend else '□'
            online_char = '■' if is_online else '□'
            if is_friend or is_online:
                fc = COLOR_ACCENT if is_friend else COLOR_FG_TERTIARY
                oc = COLOR_ACCENT if is_online else COLOR_FG_TERTIARY
                status_markup = f"[{fc}]{friend_char}[/][{oc}]{online_char}[/]"
            else:
                status_markup = f"[{COLOR_FG_TERTIARY}]□□[/]"
            status_plain_w = 2

        # 左侧前缀宽度: " ● " 或 "   " = 3
        prefix_w = 3
        # 右侧: 至少 1 格间距 + status
        right_w = 1 + status_plain_w

        # 名字可用宽度
        name_max = avail - prefix_w - right_w
        display_name = name
        name_w = cell_len(name)
        if name_w > name_max and name_max >= 2:
            display_name = _truncate_name(name, name_max)
            name_w = cell_len(display_name)

        sb_w = 2 if need_sb else 0
        pad = max(1, avail - prefix_w - name_w - status_plain_w - sb_w)

        if selected:
            left = f" [{COLOR_ACCENT}]\u25cf[/] [bold {COLOR_FG_PRIMARY}]{display_name}[/]"
        else:
            left = f"   [{COLOR_FG_SECONDARY}]{display_name}[/]"

        return f"{left}{' ' * pad}{status_markup}"

    # ── State listener ──

    def _render_card_waiting(self):
        try:
            log: RichLog = self.query_one("#online-log", RichLog)
        except Exception:
            return
        log.clear()
        log.write(RichText.from_markup(f"{M_DIM}加载名片...{M_END}"))

    def _render_card_view(self, card_data: dict):
        try:
            log: RichLog = self.query_one("#online-log", RichLog)
        except Exception:
            return
        avail_w = _widget_width(self, "online-log")
        try:
            h = log.scrollable_content_region.height
            avail_h = h if h > 0 else 15
        except Exception:
            avail_h = 15
        render_card(log, card_data, avail_w, avail_h)

    def _on_state_event(self, event: str, *args):
        if event == 'viewed_card':
            (card_data,) = args
            if self._mode == _MODE_CARD:
                self._render_card_view(card_data)
            return
        if event in ('update_users', 'update_friends', 'update_all_users'):
            # 数据变更时重置到列表模式（名片模式除外）
            if self._mode not in (_MODE_LIST, _MODE_CARD):
                self._mode = _MODE_LIST
            self._render_all()

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        st = state.online
        st.set_listener(self._on_state_event)
        self._tab = st.tab
        self._cursor = st.cursor
        self._search_query = st.search_query
        self._render_all()

    def on_unmount(self):
        if self._state_mgr:
            st = self._state_mgr.online
            st.tab = self._tab
            st.cursor = self._cursor
            st.search_query = self._search_query

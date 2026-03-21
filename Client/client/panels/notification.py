"""NotificationPanel — 通知面板（系统通知 + 好友申请 + 游戏邀请）

标签页:
  系统 — 系统通知（暂无内容）
  好友 — 好友申请列表，Enter 展开操作菜单
  游戏 — 游戏邀请列表，Enter 展开接受/拒绝

状态机:
  LIST   — j/k 移动光标，Enter 展开操作
  ACTION — j/k 在操作项间移动，Enter 执行
"""

from __future__ import annotations

from rich.text import Text as RichText
from rich.cells import cell_len
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
from ..data import GAME_STATUS_CONFIG
from ..state import ModuleStateManager
from ..widgets import _set_pane_subtitle
from ..widgets.helpers import build_tab_overflow, _widget_width, render_action_menu

_TABS = ["system", "friend", "game"]
_TAB_LABELS = {"system": "系统", "friend": "好友", "game": "游戏"}

_MODE_LIST = 'list'
_MODE_ACTION = 'action'

# 动态操作列表 — 好友申请
_PENDING_ACTIONS = [('accept', '接受'), ('reject', '拒绝'), ('delete', '删除')]
_HANDLED_ACTIONS = [('delete', '删除')]
# 动态操作列表 — 游戏邀请
_GAME_PENDING_ACTIONS = [('accept', '接受'), ('reject', '拒绝'), ('delete', '删除')]
_GAME_HANDLED_ACTIONS = [('delete', '删除')]


class NotificationPanel(Widget):
    """通知面板 — 两标签页"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._tab: str = "system"
        self._cursor: int = 0
        self._mode: str = _MODE_LIST
        self._action_cursor: int = 0
        self._state_mgr: ModuleStateManager | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="notify-header", markup=True)
        yield RichLog(
            id="notify-log", wrap=True, highlight=True,
            markup=True, max_lines=MAX_LINES_ONLINE, min_width=0,
        )

    # ── 导航协议 ──

    def _get_actions_for_current(self) -> list[tuple[str, str]]:
        """获取当前选中项的可用操作"""
        items = self._current_items()
        if not items or self._cursor >= len(items):
            return []
        item = items[self._cursor]
        if self._tab == 'game':
            status = item.get('status', 'pending') if isinstance(item, dict) else 'pending'
            if status == 'pending' and not self._is_invite_expired(item):
                return _GAME_PENDING_ACTIONS
            return _GAME_HANDLED_ACTIONS
        if isinstance(item, dict) and item.get('status') != 'pending':
            return _HANDLED_ACTIONS
        return _PENDING_ACTIONS

    def nav_down(self, count=1):
        if self._mode == _MODE_LIST:
            items = self._current_items()
            if items:
                self._cursor = (self._cursor + count) % len(items)
        elif self._mode == _MODE_ACTION:
            actions = self._get_actions_for_current()
            if actions:
                self._action_cursor = (self._action_cursor + count) % len(actions)
        self._render_list()

    def nav_up(self, count=1):
        if self._mode == _MODE_LIST:
            items = self._current_items()
            if items:
                self._cursor = (self._cursor - count) % len(items)
        elif self._mode == _MODE_ACTION:
            actions = self._get_actions_for_current()
            if actions:
                self._action_cursor = (self._action_cursor - count) % len(actions)
        self._render_list()

    def nav_enter(self):
        if self._tab == "friend":
            self._nav_enter_friend()
        elif self._tab == "game":
            self._nav_enter_game()

    def _nav_enter_friend(self):
        items = self._current_items()
        if not items or self._cursor >= len(items):
            return

        if self._mode == _MODE_LIST:
            self._action_cursor = 0
            self._mode = _MODE_ACTION
            self._render_list()
            return

        if self._mode == _MODE_ACTION:
            item = items[self._cursor]
            actions = self._get_actions_for_current()
            if not actions or self._action_cursor >= len(actions):
                return
            action_id = actions[self._action_cursor][0]
            name = item['name'] if isinstance(item, dict) else item

            if action_id == 'accept':
                try:
                    self.app.network.send({"type": "friend_accept", "name": name})
                except Exception:
                    pass
                self._state_mgr.notify.mark_friend_request(name, 'accepted')
                self._state_mgr.cmd.add_line(f"已接受 {name} 的好友申请")
            elif action_id == 'reject':
                try:
                    self.app.network.send({"type": "friend_reject", "name": name})
                except Exception:
                    pass
                self._state_mgr.notify.mark_friend_request(name, 'rejected')
                self._state_mgr.cmd.add_line(f"已拒绝 {name} 的好友申请")
            elif action_id == 'delete':
                self._state_mgr.notify.remove_friend_request(name)

            self._mode = _MODE_LIST
            self._render_list()
            if hasattr(self.screen, 'update_badges'):
                self.screen.update_badges()
            return

    def _nav_enter_game(self):
        items = self._current_items()
        if not items or self._cursor >= len(items):
            return

        if self._mode == _MODE_LIST:
            self._action_cursor = 0
            self._mode = _MODE_ACTION
            self._render_list()
            return

        if self._mode == _MODE_ACTION:
            item = items[self._cursor]
            actions = self._get_actions_for_current()
            if not actions or self._action_cursor >= len(actions):
                return
            action_id = actions[self._action_cursor][0]
            from_name = item.get('from', '')
            game = item.get('game', '')

            if action_id == 'accept':
                try:
                    self.app.network.send({
                        "type": "game_invite_accept",
                        "game": game, "from": from_name,
                    })
                except Exception:
                    pass
                # 不立即标记 — 等服务端 game_invite_result 确认
            elif action_id == 'reject':
                try:
                    self.app.network.send({
                        "type": "game_invite_reject",
                        "game": game, "from": from_name,
                    })
                except Exception:
                    pass
                self._state_mgr.notify.mark_game_invite(from_name, game, 'rejected')
            elif action_id == 'delete':
                self._state_mgr.notify.remove_game_invite(from_name, game)

            self._mode = _MODE_LIST
            self._render_list()
            if hasattr(self.screen, 'update_badges'):
                self.screen.update_badges()
            return

    def nav_back(self) -> bool:
        if self._mode == _MODE_ACTION:
            self._mode = _MODE_LIST
            self._render_list()
            return True
        if self._tab != "system":
            self._tab = "system"
            self._cursor = 0
            self._mode = _MODE_LIST
            self._render_all()
            return True
        return False

    def nav_escape(self) -> bool:
        if self._mode != _MODE_LIST:
            self._mode = _MODE_LIST
            self._render_list()
            return True
        return False

    def nav_tab_next(self):
        idx = _TABS.index(self._tab) if self._tab in _TABS else 0
        self._tab = _TABS[(idx + 1) % len(_TABS)]
        self._cursor = 0
        self._mode = _MODE_LIST
        self._render_all()

    def nav_tab_prev(self):
        idx = _TABS.index(self._tab) if self._tab in _TABS else 0
        self._tab = _TABS[(idx - 1) % len(_TABS)]
        self._cursor = 0
        self._mode = _MODE_LIST
        self._render_all()

    # ── 数据 ──

    def _current_items(self) -> list:
        st = self._state_mgr
        if not st:
            return []
        if self._tab == "system":
            return list(st.notify.system_notifications)
        elif self._tab == "friend":
            return list(st.notify.friend_requests)
        elif self._tab == "game":
            return list(st.notify.game_invites)
        return []

    # ── 渲染 ──

    def _render_all(self):
        self._render_header()
        self._render_list()
        self._update_subtitle()

    def _update_subtitle(self):
        """右下角显示未读通知数"""
        st = self._state_mgr
        if not st:
            return
        unread = st.notify.unread_count
        _set_pane_subtitle(self, f"未读({unread})")

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
        avail = _widget_width(self, "notify-header")
        tab_line = build_tab_overflow(tab_parts, active_idx, avail, COLOR_FG_TERTIARY)

        try:
            header = self.query_one("#notify-header", Static)
            header.update(tab_line)
        except Exception:
            pass

    def on_resize(self, event) -> None:
        self._render_header()

    def _game_display_name(self, game_key: str) -> str:
        """游戏 key → 显示名"""
        cfg = GAME_STATUS_CONFIG.get(game_key)
        if cfg:
            return cfg.get('name', game_key)
        return game_key

    @staticmethod
    def _is_invite_expired(item: dict) -> bool:
        import time
        return time.time() > item.get('expires_at', 0)

    def _render_list(self):
        try:
            log: RichLog = self.query_one("#notify-log", RichLog)
        except Exception:
            return

        log.clear()
        items = self._current_items()

        if not items:
            _empty = {
                'system': '暂无系统通知',
                'friend': '暂无好友申请',
                'game': '暂无游戏邀请',
            }
            log.write(RichText.from_markup(
                f"{M_DIM}{_empty.get(self._tab, '')}{M_END}"))
            return

        if self._cursor >= len(items):
            self._cursor = len(items) - 1

        if self._tab == "system":
            for i, text in enumerate(items):
                if i == self._cursor:
                    log.write(RichText.from_markup(
                        f" [{COLOR_ACCENT}]●[/] [{COLOR_FG_PRIMARY}]{text}[/]"))
                else:
                    log.write(RichText.from_markup(
                        f"   [{COLOR_FG_SECONDARY}]{text}[/]"))

        elif self._tab == "friend":
            self._render_friend_list(log, items)

        elif self._tab == "game":
            self._render_game_list(log, items)

    def _render_friend_list(self, log, items):
        for i, item in enumerate(items):
            name = item['name'] if isinstance(item, dict) else item
            status = item.get('status', 'pending') if isinstance(item, dict) else 'pending'
            sel = i == self._cursor

            if status == 'accepted':
                suffix = f" [{COLOR_FG_TERTIARY}](已接受)[/]"
            elif status == 'rejected':
                suffix = f" [{COLOR_FG_TERTIARY}](已拒绝)[/]"
            else:
                suffix = ""

            if sel:
                log.write(RichText.from_markup(
                    f" [{COLOR_ACCENT}]●[/] [bold {COLOR_FG_PRIMARY}]{name}[/]{suffix}"))
            else:
                log.write(RichText.from_markup(
                    f"   [{COLOR_FG_SECONDARY}]{name}[/]{suffix}"))

            if sel and self._mode == _MODE_ACTION:
                actions = self._get_actions_for_current()
                for line in render_action_menu(actions, self._action_cursor):
                    log.write(RichText.from_markup(line))

    def _render_game_list(self, log, items):
        for i, item in enumerate(items):
            from_name = item.get('from', '?')
            game = item.get('game', '?')
            status = item.get('status', 'pending')
            sel = i == self._cursor

            game_name = self._game_display_name(game)
            label = f"{from_name} → {game_name}"

            if status == 'accepted':
                suffix = f" [{COLOR_FG_TERTIARY}](已接受)[/]"
            elif status == 'rejected':
                suffix = f" [{COLOR_FG_TERTIARY}](已拒绝)[/]"
            elif status == 'expired' or (status == 'pending' and self._is_invite_expired(item)):
                suffix = f" [{COLOR_FG_TERTIARY}](已过期)[/]"
            else:
                suffix = ""

            if sel:
                log.write(RichText.from_markup(
                    f" [{COLOR_ACCENT}]●[/] [bold {COLOR_FG_PRIMARY}]{label}[/]{suffix}"))
            else:
                log.write(RichText.from_markup(
                    f"   [{COLOR_FG_SECONDARY}]{label}[/]{suffix}"))

            if sel and self._mode == _MODE_ACTION:
                actions = self._get_actions_for_current()
                for line in render_action_menu(actions, self._action_cursor):
                    log.write(RichText.from_markup(line))

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event in ('update_friend_requests', 'add_system_notification', 'update_game_invites'):
            if self._mode != _MODE_LIST:
                self._mode = _MODE_LIST
            self._render_all()

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        st = state.notify
        st.add_listener(self._on_state_event)
        self._tab = st.tab
        self._cursor = st.cursor
        self._render_all()

    def on_unmount(self):
        if self._state_mgr:
            self._state_mgr.notify.remove_listener(self._on_state_event)
            st = self._state_mgr.notify
            st.tab = self._tab
            st.cursor = self._cursor

"""通知面板 — 系统通知 / 好友申请 / 游戏邀请"""

from __future__ import annotations

import time

from ...config import (
    COLOR_FG_PRIMARY, COLOR_FG_TERTIARY, COLOR_HINT_TAB_DIM, ICON_INDENT,
    NF_CHECK, NF_CROSS, NF_BELL, NF_HEART, NF_SWORD,
    M_DIM, M_END,
)
from ...widgets.panel import Panel

_TABS = ["系统", "好友", "邀请"]


class NotificationPanel(Panel):
    """三标签通知面板：系统通知 / 好友申请 / 游戏邀请"""

    icon_align = True
    follow_focus = True
    tabs = list(_TABS)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._notify_state = None
        self._confirming: str = ''  # 'accept' or 'reject' or ''

    def bind_state(self, st) -> None:
        self._notify_state = st.notify
        st.notify.add_listener(self._on_event)
        self._refresh_list()

    def _on_event(self, event: str, *args):
        if event in ('update_friend_requests', 'update_game_invites',
                      'add_system_notification'):
            self._refresh_list()

    # ── 渲染 ──

    def _refresh_list(self) -> None:
        tab = _TABS[self._active]
        if tab == "系统":
            self._render_system()
        elif tab == "好友":
            self._render_friends()
        else:
            self._render_invites()

    def _render_system(self) -> None:
        ns = self._notify_state
        items = ns.system_notifications if ns else []
        if not items:
            self.update(f"{ICON_INDENT}{M_DIM}暂无通知{M_END}")
            return
        lines: list[str] = []
        for i, text in enumerate(items):
            if i == self._cursor:
                lines.append(f"[bold {COLOR_FG_PRIMARY}]{NF_BELL} {text}[/]")
            else:
                lines.append(f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{text}[/]")
        self._focus_line = self._cursor
        self.update("\n".join(lines))

    def _render_friends(self) -> None:
        ns = self._notify_state
        items = ns.friend_requests if ns else []
        if not items:
            self.update(f"{ICON_INDENT}{M_DIM}暂无好友申请{M_END}")
            return
        self._cursor = min(self._cursor, len(items) - 1)
        # 确认状态
        if self._confirming:
            r = items[self._cursor]
            tag = '接受' if self._confirming == 'accept' else '拒绝'
            self.update(self._render_confirm(
                f"{tag}好友申请: {r['name']}?", COLOR_HINT_TAB_DIM))
            return
        lines: list[str] = []
        for i, r in enumerate(items):
            name = r['name']
            status = r['status']
            if status == 'accepted':
                icon = f"[{COLOR_FG_TERTIARY}]{NF_CHECK}[/]"
                style = COLOR_FG_TERTIARY
            elif status == 'rejected':
                icon = f"[{COLOR_FG_TERTIARY}]{NF_CROSS}[/]"
                style = COLOR_FG_TERTIARY
            else:
                # pending
                if i == self._cursor:
                    icon = f"[{COLOR_FG_PRIMARY}]{NF_HEART}[/]"
                    style = f"bold {COLOR_FG_PRIMARY}"
                else:
                    icon = f"[{COLOR_HINT_TAB_DIM}]{NF_HEART}[/]"
                    style = COLOR_HINT_TAB_DIM
            if i == self._cursor and status == 'pending':
                lines.append(f"{icon} [{style}]{name}[/]")
            elif status != 'pending':
                tag = "已接受" if status == 'accepted' else "已拒绝"
                lines.append(f"{icon} [{style}]{name} {tag}[/]")
            else:
                lines.append(f"[{style}]{ICON_INDENT}{name}[/]")
        self._focus_line = self._cursor
        self.update("\n".join(lines))

    def _render_invites(self) -> None:
        ns = self._notify_state
        items = ns.game_invites if ns else []
        if not items:
            self.update(f"{ICON_INDENT}{M_DIM}暂无游戏邀请{M_END}")
            return
        self._cursor = min(self._cursor, len(items) - 1)
        # 确认状态
        if self._confirming == 'accept_invite':
            inv = items[self._cursor]
            label = f"{inv['from']} → {inv['game']}"
            self.update(self._render_confirm(
                f"接受邀请: {label}?", COLOR_HINT_TAB_DIM))
            return
        if self._confirming == 'reject_invite':
            inv = items[self._cursor]
            label = f"{inv['from']} → {inv['game']}"
            self.update(self._render_confirm(
                f"拒绝邀请: {label}?", COLOR_HINT_TAB_DIM))
            return
        now = time.time()
        lines: list[str] = []
        for i, inv in enumerate(items):
            sender = inv['from']
            game = inv['game']
            status = inv['status']
            expired = inv.get('expires_at', 0) <= now
            label = f"{sender} → {game}"
            if status == 'accepted':
                icon = f"[{COLOR_FG_TERTIARY}]{NF_CHECK}[/]"
                lines.append(f"{icon} [{COLOR_FG_TERTIARY}]{label} 已接受[/]")
            elif status == 'rejected' or expired:
                icon = f"[{COLOR_FG_TERTIARY}]{NF_CROSS}[/]"
                tag = "已过期" if expired and status == 'pending' else "已拒绝"
                lines.append(f"{icon} [{COLOR_FG_TERTIARY}]{label} {tag}[/]")
            else:
                # pending & not expired
                if i == self._cursor:
                    icon = f"[{COLOR_FG_PRIMARY}]{NF_SWORD}[/]"
                    lines.append(f"{icon} [bold {COLOR_FG_PRIMARY}]{label}[/]")
                else:
                    lines.append(
                        f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{label}[/]")
        self._focus_line = self._cursor
        self.update("\n".join(lines))

    # ── 标签切换 ──

    def switch_tab(self, index: int) -> None:
        super().switch_tab(index)
        self._cursor = 0
        self._refresh_list()

    # ── 导航 ──

    def _item_count(self) -> int:
        ns = self._notify_state
        if not ns:
            return 0
        tab = _TABS[self._active]
        if tab == "系统":
            return len(ns.system_notifications)
        elif tab == "好友":
            return len(ns.friend_requests)
        else:
            return len(ns.game_invites)

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._refresh_list()

    def nav(self, action: str) -> None:
        if action in ("tab_prev", "tab_next"):
            self._confirming = ''
            super().nav(action)
            return
        # 确认状态处理
        if self._confirming:
            def _on_yes():
                if self._confirming == 'accept':
                    self._do_accept()
                elif self._confirming == 'accept_invite':
                    self._do_accept_invite_confirmed()
                elif self._confirming == 'reject_invite':
                    self._do_reject_invite()
                else:
                    self._do_reject()
                self._confirming = ''
                self._refresh_list()
            def _on_dismiss():
                self._confirming = ''
                self._refresh_list()
            self._nav_confirm(action, _on_yes, _on_dismiss)
            self._refresh_list()
            return
        count = self._item_count()
        if action == "up":
            if self._move_cursor(-1, count):
                self._refresh_list()
        elif action == "down":
            if self._move_cursor(1, count):
                self._refresh_list()
        elif action == "enter":
            self._action_accept()
        elif action == "delete":
            self._action_reject()

    def _action_accept(self) -> None:
        """Enter: 进入确认状态"""
        ns = self._notify_state
        if not ns:
            return
        tab = _TABS[self._active]
        if tab == "好友":
            items = ns.friend_requests
            if 0 <= self._cursor < len(items):
                r = items[self._cursor]
                if r['status'] == 'pending':
                    self._confirming = 'accept'
                    self._confirm_cursor = 0
                    self._refresh_list()
        elif tab == "邀请":
            items = ns.game_invites
            now = time.time()
            if 0 <= self._cursor < len(items):
                inv = items[self._cursor]
                if inv['status'] == 'pending' and inv.get('expires_at', 0) > now:
                    self._confirming = 'accept_invite'
                    self._confirm_cursor = 0
                    self._refresh_list()

    def _action_reject(self) -> None:
        """d: 进入拒绝确认状态"""
        ns = self._notify_state
        if not ns:
            return
        tab = _TABS[self._active]
        if tab == "好友":
            items = ns.friend_requests
            if 0 <= self._cursor < len(items):
                r = items[self._cursor]
                if r['status'] == 'pending':
                    self._confirming = 'reject'
                    self._confirm_cursor = 0
                    self._refresh_list()
        elif tab == "邀请":
            items = ns.game_invites
            if 0 <= self._cursor < len(items):
                inv = items[self._cursor]
                if inv['status'] == 'pending':
                    self._confirming = 'reject_invite'
                    self._confirm_cursor = 0
                    self._refresh_list()

    def _do_accept(self) -> None:
        """确认后执行接受"""
        ns = self._notify_state
        if not ns:
            return
        tab = _TABS[self._active]
        if tab == "好友":
            items = ns.friend_requests
            if 0 <= self._cursor < len(items):
                r = items[self._cursor]
                self.app.network.send({
                    "type": "friend_accept", "name": r['name']})

    def _do_reject(self) -> None:
        """确认后执行拒绝"""
        ns = self._notify_state
        if not ns:
            return
        tab = _TABS[self._active]
        if tab == "好友":
            items = ns.friend_requests
            if 0 <= self._cursor < len(items):
                r = items[self._cursor]
                self.app.network.send({
                    "type": "friend_reject", "name": r['name']})

    def _do_accept_invite(self, inv: dict) -> None:
        """直接接受游戏邀请"""
        self.app.network.send({
            "type": "game_invite_accept",
            "game": inv['game'], "from": inv['from']})

    def _do_accept_invite_confirmed(self) -> None:
        """确认后接受游戏邀请"""
        ns = self._notify_state
        if not ns:
            return
        items = ns.game_invites
        if 0 <= self._cursor < len(items):
            inv = items[self._cursor]
            self._do_accept_invite(inv)

    def _do_reject_invite(self) -> None:
        """确认后拒绝游戏邀请"""
        ns = self._notify_state
        if not ns:
            return
        items = ns.game_invites
        if 0 <= self._cursor < len(items):
            inv = items[self._cursor]
            self.app.network.send({
                "type": "game_invite_reject", "game": inv['game']})
            ns.remove_game_invite(inv['from'], inv['game'])

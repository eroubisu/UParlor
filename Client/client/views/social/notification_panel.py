"""通知面板 — 系统通知 / 好友申请 / 游戏邀请"""

from __future__ import annotations

import time
from rich.markup import escape

from ...config import (
    COLOR_FG_PRIMARY, COLOR_FG_TERTIARY, COLOR_HINT_TAB_DIM, ICON_INDENT,
    NF_CHECK, NF_CROSS, NF_BELL, NF_HEART, NF_SWORD,
    M_DIM, M_END,
)
from ...widgets.panel import Panel
from ...window_engine import Option, SurfaceState

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
        self._action_menu = False
        self._action_item: dict | None = None

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
            self.show_surface(SurfaceState.empty("暂无通知"))
            return
        self.set_options(
            (Option(str(index), f"{NF_BELL} {escape(text)}", markup=True)
             for index, text in enumerate(items)),
            "notifications:system",
        )
        self._focus_line = self.selected_line()
        self.update(self.render_options())

    def _render_friends(self) -> None:
        ns = self._notify_state
        items = ns.friend_requests if ns else []
        if not items:
            self.show_surface(SurfaceState.empty("暂无好友申请"))
            return
        if self._action_menu:
            self._render_actions()
            return
        # 确认状态
        if self._confirming:
            if self._action_item is None:
                return
            tag = '接受' if self._confirming == 'accept' else '拒绝'
            self.update(self._render_confirm(
                f"{tag}好友申请: {self._action_item['name']}?",
                COLOR_HINT_TAB_DIM,
            ))
            return
        options = []
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
                icon = NF_HEART
                style = COLOR_HINT_TAB_DIM
            if status != 'pending':
                tag = "已接受" if status == 'accepted' else "已拒绝"
                label = f"{icon} [{style}]{escape(name)} {tag}[/]"
            else:
                label = f"{icon} {escape(name)}"
            options.append(Option(
                str(i), label, enabled=status == "pending",
                data=r, markup=True,
            ))
        self.set_options(options, "notifications:friends")
        self._focus_line = self.selected_line()
        self.update(self.render_options())

    def _render_invites(self) -> None:
        ns = self._notify_state
        items = ns.game_invites if ns else []
        if not items:
            self.show_surface(SurfaceState.empty("暂无游戏邀请"))
            return
        if self._action_menu:
            self._render_actions()
            return
        # 确认状态
        if self._confirming == 'accept_invite':
            if self._action_item is None:
                return
            inv = self._action_item
            label = f"{inv['from']} → {inv['game']}"
            self.update(self._render_confirm(
                f"接受邀请: {label}?", COLOR_HINT_TAB_DIM))
            return
        if self._confirming == 'reject_invite':
            if self._action_item is None:
                return
            inv = self._action_item
            label = f"{inv['from']} → {inv['game']}"
            self.update(self._render_confirm(
                f"拒绝邀请: {label}?", COLOR_HINT_TAB_DIM))
            return
        now = time.time()
        options = []
        for i, inv in enumerate(items):
            sender = inv['from']
            game = inv['game']
            status = inv['status']
            expired = inv.get('expires_at', 0) <= now
            label = f"{sender} → {game}"
            if status == 'accepted':
                icon = f"[{COLOR_FG_TERTIARY}]{NF_CHECK}[/]"
                rendered = f"{icon} [{COLOR_FG_TERTIARY}]{escape(label)} 已接受[/]"
                enabled = False
            elif status == 'rejected' or expired:
                icon = f"[{COLOR_FG_TERTIARY}]{NF_CROSS}[/]"
                tag = "已过期" if expired and status == 'pending' else "已拒绝"
                rendered = f"{icon} [{COLOR_FG_TERTIARY}]{escape(label)} {tag}[/]"
                enabled = False
            else:
                rendered = f"{NF_SWORD} {escape(label)}"
                enabled = True
            options.append(Option(
                str(i), rendered, enabled=enabled, data=inv, markup=True,
            ))
        self.set_options(options, "notifications:invites")
        self._focus_line = self.selected_line()
        self.update(self.render_options())

    # ── 标签切换 ──

    def switch_tab(self, index: int) -> None:
        self._action_menu = False
        self._action_item = None
        self._confirming = ""
        super().switch_tab(index)
        self._refresh_list()

    def _render_actions(self) -> None:
        self.set_options(
            (
                Option("accept", "接受"),
                Option("reject", "拒绝"),
                Option("return", "返回"),
            ),
            "notification-actions",
        )
        self.update(self.render_options())

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

    def reflow_content(self) -> None:
        self._refresh_list()

    def nav(self, action: str) -> None:
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
                self._action_item = None
                self._refresh_list()
            def _on_dismiss():
                self._confirming = ''
                self._action_item = None
                self._refresh_list()
            self._nav_confirm(action, _on_yes, _on_dismiss)
            self._refresh_list()
            return
        if self._action_menu:
            selected = self.selection.handle(action)
            if action in ("up", "down"):
                self._refresh_list()
            elif selected is not None:
                if selected.id == "return":
                    self._action_menu = False
                    self._action_item = None
                else:
                    tab = _TABS[self._active]
                    if (
                        tab == "邀请"
                        and selected.id == "accept"
                        and self._action_item is not None
                        and self._action_item.get("expires_at", 0) <= time.time()
                    ):
                        self._action_menu = False
                        self._action_item = None
                        self.app.notify("邀请已过期。")
                        self._refresh_list()
                        return
                    self._confirming = (
                        selected.id
                        if tab == "好友"
                        else f"{selected.id}_invite"
                    )
                    self._action_menu = False
                self._refresh_list()
            return
        if action in ("tab_prev", "tab_next"):
            super().nav(action)
            return
        if action in ("up", "down"):
            if self.selection.move(-1 if action == "up" else 1):
                self._refresh_list()
        elif action == "enter":
            selected = self.selected_option
            if selected is not None and _TABS[self._active] != "系统":
                self._action_item = selected.data
                self._action_menu = True
                self._refresh_list()

    def _do_accept(self) -> None:
        """确认后执行接受"""
        ns = self._notify_state
        if not ns:
            return
        tab = _TABS[self._active]
        if tab == "好友":
            if self._action_item is not None:
                r = self._action_item
                self.app.network.send({
                    "type": "friend_accept", "name": r['name']})

    def _do_reject(self) -> None:
        """确认后执行拒绝"""
        ns = self._notify_state
        if not ns:
            return
        tab = _TABS[self._active]
        if tab == "好友":
            if self._action_item is not None:
                r = self._action_item
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
        if self._action_item is not None:
            inv = self._action_item
            self._do_accept_invite(inv)

    def _do_reject_invite(self) -> None:
        """确认后拒绝游戏邀请"""
        ns = self._notify_state
        if not ns:
            return
        if self._action_item is not None:
            inv = self._action_item
            self.app.network.send({
                "type": "game_invite_reject", "game": inv['game']})
            ns.remove_game_invite(inv['from'], inv['game'])

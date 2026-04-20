"""导航路由 — 浮窗打开、事件分发"""

from __future__ import annotations

from .widgets.panel import PlayerSelected
from .views import (
    ChatWindow, ProfileWindow, OnlineWindow,
    NotificationWindow, GameSelectWindow,
)
from .views.system.tutorial import TutorialWindow, TutorialPanel
from .views.system.docs import DocsWindow
from .views.system.settings import SettingsWindow


class NavigationMixin:
    """浮窗打开与事件路由"""

    def _open_chat(self):
        """打开聊天浮窗（仅大厅模式）"""
        if self.mode == "login":
            return
        cw = self.query_one("#chat-window", ChatWindow)
        cw.bind_state(self.state)
        cw.show()
        # 清除所有私聊未读
        if self.state.chat.dm_unread:
            self.state.chat.clear_dm_unread()
            self.update_badges()
        self._push_overlay("chat-window")

    def _open_dm(self, peer: str):
        """打开私聊浮窗并定位到指定玩家"""
        if self.mode == "login":
            return
        self._close_overlay()
        cw = self.query_one("#chat-window", ChatWindow)
        cw.bind_state(self.state)
        cw.show()
        cw.open_dm(peer)
        # 清除所有私聊未读
        if self.state.chat.dm_unread:
            self.state.chat.clear_dm_unread()
            self.update_badges()
        self._push_overlay("chat-window")

    def _open_profile(self):
        """打开档案浮窗（仅大厅模式）"""
        if self.mode == "login":
            return
        pw = self.query_one("#profile-window", ProfileWindow)
        pw.bind_state(self.state)
        pw.show()
        self._push_overlay("profile-window")

    def _open_profile_card(self, data: dict):
        """打开他人名片浮窗"""
        pw = self.query_one("#profile-window", ProfileWindow)
        pw.bind_state(self.state)
        my_name = self.state.status.player_data.get('name', '')
        is_self = data.get('name') == my_name
        friends = self.state.online.friends or []
        pw.show_player_card(data, is_self=is_self, friends=friends)
        pw.show()
        self._push_overlay("profile-window")

    def on_player_selected(self, event: PlayerSelected) -> None:
        """统一处理玩家选中 → 请求名片"""
        event.stop()
        self._pending_profile_card = True
        self.app.network.send({"type": "get_profile_card", "target": event.name})

    def _on_online_event(self, event: str, *args):
        if event == 'viewed_card' and getattr(self, '_pending_profile_card', False):
            self._pending_profile_card = False
            self._open_profile_card(args[0])

    def _open_online(self):
        """打开在线玩家浮窗（仅大厅模式）"""
        if self.mode == "login":
            return
        ow = self.query_one("#online-window", OnlineWindow)
        ow.bind_state(self.state)
        ow.show()
        self._push_overlay("online-window")

    def _open_notification(self):
        """打开通知浮窗（仅大厅模式）"""
        if self.mode == "login":
            return
        nw = self.query_one("#notification-window", NotificationWindow)
        nw.bind_state(self.state)
        nw.show()
        # 标记通知已读
        self.state.notify.mark_badge_seen()
        self.update_badges()
        self._push_overlay("notification-window")

    def _open_game_select(self):
        """打开游戏选择浮窗"""
        if self.mode == "login":
            return
        gw = self.query_one("#game-select-window", GameSelectWindow)
        gw.bind_state(self.state, self.app.send_command)
        gw.show()
        self._push_overlay("game-select-window")

    def _open_tutorial(self):
        """打开教程 — 登录前作为主窗口，登录后作为浮窗"""
        tw = self.query_one("#tutorial-window", TutorialWindow)
        if not self.logged_in:
            # 登录前：主窗口模式
            self.query_one("#login-window").remove_class("visible")
            tw.show()
            self.mode = "tutorial"
        else:
            # 登录后：浮窗模式
            tw.show()
            self._push_overlay("tutorial-window")

    def on_tutorial_panel_tutorial_done(self, _msg: TutorialPanel.TutorialDone) -> None:
        """教程完成 — 持久化到本地设备，切换到登录"""
        from .storage import set_tutorial_done
        set_tutorial_done()
        self._finish_tutorial()

    def _finish_tutorial(self):
        """关闭教程"""
        tw = self.query_one("#tutorial-window")
        tw.hide()
        if self.mode == "tutorial":
            # 主窗口模式 → 切换到登录
            self.query_one("#login-window").add_class("visible")
            self.mode = "login"

    def _open_docs(self):
        """打开说明文档浮窗"""
        dw = self.query_one("#docs-window", DocsWindow)
        dw.show()
        self._push_overlay("docs-window")

    def _open_settings(self):
        """打开设置浮窗"""
        sw = self.query_one("#settings-window", SettingsWindow)
        sw.show()
        self._push_overlay("settings-window")

    _OPEN_DISPATCH: dict[str, str] = {
        'tutorial': '_open_tutorial',
        'docs': '_open_docs',
        'profile': '_open_profile',
    }

    def _dispatch_open(self, target: str) -> None:
        method = self._OPEN_DISPATCH.get(target)
        if method:
            getattr(self, method)()

    def on_settings_panel_selected(self, event) -> None:
        """设置面板选中项"""
        event.stop()
        self._close_overlay()
        self._dispatch_open(event.target)

    def on_login_panel_open_guide(self, event) -> None:
        """登录页面请求打开教程/文档"""
        event.stop()
        self._dispatch_open(event.target)

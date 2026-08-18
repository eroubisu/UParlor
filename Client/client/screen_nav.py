"""导航路由 — 引擎未覆盖的业务事件路由

引擎接管 (无需手写): 已注册窗口的 compose / 打开 / 关闭 / 主窗口切换
本文件仅保留:
- 玩家选中 → 名片请求往返 (异步业务流)
- DM 跳转 (chat 窗口需要 peer 参数)
- 教程窗口生命周期 (始终是 primary, 但完成后要恢复上次的 primary)
- 设置菜单选项 → 子窗口路由
"""

from __future__ import annotations

from .widgets.panel import PlayerSelected
from .views.system.remote import RemotePanel
from .views.system.tutorial import TutorialPanel
from .config import M_DIM, M_END
from .window_engine.text import plain_text


class NavigationMixin:
    """业务事件路由"""

    # ── 玩家选中 → 请求名片往返 ──

    def on_player_selected(self, event: PlayerSelected) -> None:
        """统一处理玩家选中 → 请求名片"""
        event.stop()
        self._pending_profile_card = True
        self.app.network.send({"type": "get_profile_card", "target": event.name})

    def _on_online_event(self, event: str, *args):
        if event == 'viewed_card' and getattr(self, '_pending_profile_card', False):
            self._pending_profile_card = False
            self.engine.open('profile-window', card={'data': args[0]})

    # ── DM 跳转 (chat 窗口带参数) ──

    def _open_dm(self, peer: str):
        """打开私聊浮窗并定位到指定玩家"""
        self.engine.open('chat-window', dm_peer=peer)

    # ── 教程窗口 (始终 primary; 完成后恢复上次 primary) ──

    _tutorial_return_to: str = ""  # 教程关闭后要恢复的主窗口 id

    def _open_tutorial(self):
        """打开教程: 记住当前 primary, 切到 tutorial-window"""
        current = getattr(self.engine, '_primary_id', None)
        if current and current != 'tutorial-window':
            self._tutorial_return_to = current
        self.engine.set_primary('tutorial-window')
        if not self.logged_in:
            self.mode = "tutorial"

    def on_tutorial_panel_tutorial_done(self, _msg: TutorialPanel.TutorialDone) -> None:
        """教程完成 — 持久化到本地设备并关闭"""
        from .storage import set_tutorial_done
        set_tutorial_done()
        self._finish_tutorial()

    def _finish_tutorial(self):
        """关闭教程, 回到上次的 primary (或 login)"""
        target = self._tutorial_return_to or 'login-window'
        self._tutorial_return_to = ''
        self.engine.set_primary(target)
        if target == 'login-window':
            self.mode = "login"
        elif target == 'lobby-window':
            self.mode = "game"

    # ── settings 菜单选项 → 子窗口路由 ──

    _SETTINGS_TO_WINDOW: dict[str, str] = {
        'docs': 'docs-window',
    }
    _SETTINGS_TO_METHOD: dict[str, str] = {
        'tutorial': '_open_tutorial',
    }

    def _dispatch_open(self, target: str) -> None:
        wid = self._SETTINGS_TO_WINDOW.get(target)
        if wid:
            self.engine.open(wid)
            return
        method = self._SETTINGS_TO_METHOD.get(target)
        if method:
            getattr(self, method)()

    def on_settings_panel_selected(self, event) -> None:
        """设置面板选中项 → 打开目标"""
        event.stop()
        self._dispatch_open(event.target)

    def on_settings_panel_quit_requested(self, event) -> None:
        event.stop()
        self.app.action_quit()

    def on_root_menu_panel_selected(self, event) -> None:
        """Keep the root menu covering the old window until the target is ready."""
        event.stop()
        self.engine.open_from_popup("root-menu-window", event.window_id)

    def on_companion_panel_open_creation(self, event) -> None:
        event.stop()
        self.engine.open("companion-creation-window")

    def on_companion_creation_panel_created(self, event) -> None:
        event.stop()
        window = self.engine.get_window("companion-window")
        if window is not None:
            window.refresh_companion()
        self.engine.open("companion-window")

    def on_status_panel_open_chat_style(self, event) -> None:
        event.stop()
        self.engine.open("chat-style-window")

    def on_chat_style_panel_finished(self, event) -> None:
        event.stop()
        self.engine.open("profile-window")

    def on_login_panel_open_guide(self, event) -> None:
        """登录页面请求打开教程/文档"""
        event.stop()
        self._dispatch_open(event.target)

    # ── iOS 手柄（uremote）──

    def on_settings_panel_remote_toggled(self, event) -> None:
        """设置面板切换 iOS 连接开关"""
        event.stop()
        self._toggle_remote()

    def on_remote_panel_back_requested(
        self, event: RemotePanel.BackRequested,
    ) -> None:
        """关闭连接浮窗，但保持网页手柄服务。"""
        event.stop()
        self.engine.close("remote-window")

    def _toggle_remote(self) -> None:
        remote = self.app.remote
        if remote.state == "off":
            try:
                remote.enable()
            except Exception as exc:
                self.state.cmd.add_line(
                    f"{M_DIM}iOS 连接开启失败: {exc}{M_END}"
                )
                return
            # 用最近的记录面板行填充（转纯文本）
            for line in self.state.cmd.lines[-10:]:
                remote.record(plain_text(line))
            self.engine.open("remote-window")
        else:
            remote.disable()
            self.engine.close("remote-window")

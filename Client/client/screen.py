"""
GameScreen — 主屏幕（LOGIN / GAME 双模式）
"""

from __future__ import annotations

from textual.screen import Screen
from textual.widgets import Static, Input
from textual.containers import Horizontal
from textual.app import ComposeResult
from textual.reactive import reactive
from textual import events

from .state import ModuleStateManager
from .views import LoginWindow, LobbyWindow, ChatWindow, ProfileWindow, OnlineWindow, NotificationWindow, GameSelectWindow, WaitingWindow, GameWindow
from .views.tutorial import TutorialWindow
from .views.docs import DocsWindow
from .views.settings import SettingsWindow
from .widgets.panel import PlayerSelected
from .widgets.which_key import WhichKeyPanel
from .config import NF_HOME, NF_BELL, NF_HEART, NF_ONLINE, NF_SWORD, DEFAULT_HOST

# 模块名 → widget ID
_MODULE_IDS = {
    'login': 'login-panel',
    'cmd': 'cmd-panel',
    'room_search': 'room-search',
    'game_detail': 'game-detail',
    'room_controls': 'room-controls',
}

# key → nav action
_KEY_ALIAS = {
    'left': 'h', 'down': 'j', 'up': 'k', 'right': 'l',
    'a': 'h', 's': 'j', 'w': 'k', 'd': 'l',
    'c': 'space', 'x': 'escape', 'z': 'enter', 'q': 'escape',
    'ctrl+left_square_bracket': 'escape',
}

_KEY_ACTION = {
    'j': 'down', 'k': 'up',
    'h': 'tab_prev', 'l': 'tab_next',
    'enter': 'enter',
    'd': 'delete',
}


class GameScreen(Screen):

    mode = reactive("login")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.logged_in = False
        self.current_location = "lobby"
        self.state = ModuleStateManager()
        self._mode = 'normal'  # normal / insert / which_key / focus
        self._sticky_insert = False  # True = 大写 I，提交后不退出
        self._overlay_stack: list[str] = []  # 浮窗打开顺序 (widget id)

    def compose(self) -> ComposeResult:
        yield LoginWindow(id="login-window", classes="visible")
        yield LobbyWindow(id="lobby-window")
        yield ChatWindow(id="chat-window")
        yield ProfileWindow(id="profile-window")
        yield OnlineWindow(id="online-window")
        yield NotificationWindow(id="notification-window")
        yield GameSelectWindow(id="game-select-window")
        yield WaitingWindow(id="waiting-window")
        yield GameWindow(id="game-window")
        yield TutorialWindow(id="tutorial-window")
        yield DocsWindow(id="docs-window")
        yield SettingsWindow(id="settings-window")
        yield WhichKeyPanel(id="which-key-overlay")
        with Horizontal(id="footer-bar"):
            yield Static(" NORMAL ", id="mode-indicator")
            yield Static(f" {NF_HOME} HOME", id="location-indicator")
            yield Static("", id="footer-spacer")
            yield Static("", id="badge-indicator")
            yield Static(f" {NF_ONLINE} ---- ", id="connection-status")

    def on_mount(self) -> None:
        self.app.connect_to_server(DEFAULT_HOST)

    # ── 模块访问（dispatch.py 接口）──

    def get_module(self, module_name: str):
        wid = _MODULE_IDS.get(module_name)
        if not wid:
            return None
        # room_controls 存在于多个窗口，优先从当前活跃窗口查找
        if module_name == 'room_controls':
            w = self._get_active_window()
            if w:
                try:
                    return w.query_one(f"#{wid}")
                except Exception:
                    pass
        try:
            return self.query_one(f"#{wid}")
        except Exception:
            return None

    # ── 布局切换（dispatch.py 接口）──

    async def _rebuild_to_game_layout(self):
        if self.mode == "login":
            if self._mode != 'normal':
                self._to_normal()
            self.query_one("#login-window").remove_class("visible")
            lobby = self.query_one("#lobby-window", LobbyWindow)
            lobby.add_class("visible")
            lobby.bind_state(self.state)
            self.state.game_board.add_listener(self._on_room_state_change)
            self.state.online.add_listener(self._on_online_event)
            self.mode = "game"

    async def _rebuild_to_login_layout(self):
        self.query_one("#lobby-window").remove_class("visible")
        self.query_one("#waiting-window").remove_class("visible")
        self.query_one("#game-window").remove_class("visible")
        self.query_one("#login-window").add_class("visible")
        self.state = ModuleStateManager()
        self.mode = "login"

    # ── 徽章（dispatch.py 接口）──

    def update_badges(self):
        badge = self.query_one("#badge-indicator", Static)
        parts = []
        if not self.state.notify.badge_seen:
            notify_unread = self.state.notify.unread_count + self.state.notify.unread_game_count
            if notify_unread:
                parts.append(f"{NF_BELL} {notify_unread}")
        dm_unread = sum(self.state.chat.dm_unread.values())
        if dm_unread:
            parts.append(f"{NF_HEART} {dm_unread}")
        text = f" {' '.join(parts)} " if parts else ""
        badge.update(text)
        badge.refresh()

    # ── 位置/命令（dispatch.py 接口）──

    def _update_hint_bar(self):
        from .protocol.commands import get_game_tabs
        from .views.room_controls import RoomControlsPanel
        tabs = get_game_tabs()
        for rc in self.query(RoomControlsPanel):
            rc.update_commands(tabs)

    def _update_location(self, location: str, location_path: str | None = None):
        self.current_location = location
        self.state.location = location
        display = location_path or location
        icon = NF_SWORD if '#' in location else NF_HOME
        self.query_one("#location-indicator", Static).update(f" {icon} {display}")


    # ── 主窗口切换 ──

    def _switch_main_window(self, target: str) -> None:
        """切换主窗口：'lobby' / 'waiting' / 'game'"""
        mapping = {
            'lobby': '#lobby-window',
            'waiting': '#waiting-window',
            'game': '#game-window',
        }
        for key, wid in mapping.items():
            w = self.query_one(wid)
            if key == target:
                if not w.has_class('visible'):
                    if hasattr(w, 'bind_state'):
                        if key in ('waiting', 'game'):
                            w.bind_state(self.state, self.app.send_command)
                        else:
                            w.bind_state(self.state)
                    w.show()
            else:
                w.remove_class('visible')

    def _on_room_state_change(self, event: str, *args) -> None:
        """监听 game_board state 变化，自动切换主窗口"""
        if event == 'update_room':
            rd = args[0] if args else {}
            rs = rd.get('room_state', '')
            if rs == 'lobby':
                # 进入游戏大厅 — 切回 lobby 窗口
                self._close_game_select_overlay()
                self._switch_main_window('lobby')
            elif rs == 'waiting':
                self._close_game_select_overlay()
                self._switch_main_window('waiting')
            elif rs in ('playing', 'finished'):
                self._switch_main_window('game')
        elif event == 'clear':
            self._switch_main_window('lobby')

    def _close_game_select_overlay(self):
        """关闭游戏选择浮窗"""
        try:
            gw = self.query_one("#game-select-window")
            if gw.has_class("visible"):
                gw.remove_class("visible")
                self._overlay_stack = [w for w in self._overlay_stack if w != "game-select-window"]
        except Exception:
            pass

    # ── 模式切换 ──

    def _set_mode(self, mode: str, indicator: str) -> None:
        self._mode = mode
        self.query_one("#mode-indicator", Static).update(f" {indicator} ")

    def _to_normal(self) -> None:
        if self._mode == 'insert':
            self.set_focus(None)
            from . import ime
            ime.on_insert_leave()
        elif self._mode in ('which_key', 'focus'):
            self.query_one("#which-key-overlay", WhichKeyPanel).hide()
        self._set_mode('normal', 'NORMAL')

    def _enter_insert(self, sticky: bool = False):
        w = self._get_focused_widget()
        if not w:
            return
        inp = w.get_input_widget() if hasattr(w, 'get_input_widget') else None
        if not inp:
            return
        self._sticky_insert = sticky
        self._set_mode('insert', 'INSERT')
        inp.disabled = False
        inp.focus()
        from . import ime
        ime.on_insert_enter()

    def _enter_which_key(self):
        self.query_one("#which-key-overlay", WhichKeyPanel).show_root()
        self._set_mode('which_key', 'NORMAL')

    def _enter_focus(self):
        self.query_one("#which-key-overlay", WhichKeyPanel).show_focus()
        self._set_mode('focus', 'WINDOW')

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self._sticky_insert:
            self._to_normal()

    # ── 键盘 ──

    def on_paste(self, event: events.Paste) -> None:
        pass

    def on_key(self, event) -> None:
        mode = self._mode

        # INSERT — 只拦截 Escape
        if mode == 'insert':
            if event.key == 'escape':
                event.prevent_default()
                event.stop()
                self._to_normal()
            return

        event.prevent_default()
        event.stop()

        # WHICH_KEY — 按键匹配菜单项
        if mode == 'which_key':
            key = event.key
            if key == 'escape':
                self._to_normal()
            elif key == 'w':
                self._enter_focus()
            elif key == 'c':
                self._to_normal()
                self._open_chat()
            elif key == 'o':
                self._to_normal()
                self._open_online()
            elif key == 'n':
                self._to_normal()
                self._open_notification()
            elif key == 'g':
                self._to_normal()
                self._open_game_select()
            elif key == 's':
                self._to_normal()
                self._open_settings()
            return

        # FOCUS — hjkl 切换面板聚焦（一次性：选方向→移动→回到 normal）
        if mode == 'focus':
            key = event.key
            if key == 'escape':
                self._to_normal()
            elif key in ('h', 'j', 'k', 'l'):
                w = self._get_active_window()
                if w:
                    w.focus_move(key)
                self._to_normal()
            return

        # NORMAL
        key = _KEY_ALIAS.get(event.key, event.key)

        if key == 'escape':
            if self._close_overlay():
                return
            w = self._get_active_window()
            if w and hasattr(w, 'nav'):
                w.nav('escape')
            return

        if key == 'space':
            if self.mode == 'login':
                return
            self._enter_which_key()
            return

        if key in ('i', 'I'):
            self._enter_insert(sticky=(key == 'I'))
            return

        action = _KEY_ACTION.get(key)
        if action:
            w = self._get_active_window()
            if w and hasattr(w, 'nav'):
                w.nav(action)

    # ── 辅助 ──

    def _open_chat(self):
        """打开聊天浮窗（仅大厅模式）"""
        if self.mode == "login":
            return
        cw = self.query_one("#chat-window", ChatWindow)
        cw.bind_state(self.state)
        cw.show()
        # 清除所有私聊未读
        if self.state.chat.dm_unread:
            self.state.chat.dm_unread.clear()
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
            self.state.chat.dm_unread.clear()
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
        self.state.notify.badge_seen = True
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
        """打开新手教程浮窗"""
        tw = self.query_one("#tutorial-window", TutorialWindow)
        tw.show()
        self._push_overlay("tutorial-window")

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

    def _push_overlay(self, wid: str) -> None:
        if wid in self._overlay_stack:
            self._overlay_stack.remove(wid)
        self._overlay_stack.append(wid)

    def _close_overlay(self) -> bool:
        """关闭最顶层 overlay 浮窗，返回是否有浮窗被关闭"""
        while self._overlay_stack:
            wid = self._overlay_stack.pop()
            try:
                w = self.query_one(f"#{wid}")
            except Exception:
                continue
            if w.has_class("visible"):
                w.remove_class("visible")
                return True
        return False

    def _get_active_window(self):
        """获取当前活动的 Window（overlay 浮窗优先，后开的在前）"""
        for wid in reversed(self._overlay_stack):
            try:
                w = self.query_one(f"#{wid}")
                if w.has_class("visible"):
                    return w
            except Exception:
                continue
        if self.mode == "login":
            try:
                return self.query_one("#login-window")
            except Exception:
                return None
        for wid in ('#game-window', '#waiting-window', '#lobby-window'):
            try:
                w = self.query_one(wid)
                if w.has_class('visible'):
                    return w
            except Exception:
                continue
        return None

    def _get_focused_widget(self):
        for wid in reversed(self._overlay_stack):
            try:
                w = self.query_one(f"#{wid}")
                if w.has_class("visible"):
                    return w.focused_panel
            except Exception:
                continue
        if self.mode == "login":
            return self.get_module('login')
        for wid in ('#game-window', '#waiting-window', '#lobby-window'):
            try:
                w = self.query_one(wid)
                if w.has_class('visible'):
                    return w.focused_panel
            except Exception:
                continue
        return None

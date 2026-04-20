"""
GameScreen — 主屏幕（LOGIN / GAME 双模式）

职责拆分：
  screen_modes.py   — 输入模式状态机（normal/insert/which_key/focus）
  screen_overlay.py — 浮窗栈管理（push/pop/toggle）
  screen_nav.py     — 导航路由（打开浮窗、事件分发）
"""

from __future__ import annotations

from textual.screen import Screen
from textual.widgets import Static, Input
from textual.containers import Horizontal
from textual.app import ComposeResult
from textual.reactive import reactive
from textual import events

from .state import ModuleStateManager
from .views import (
    LoginWindow, LobbyWindow, ChatWindow, ProfileWindow,
    OnlineWindow, NotificationWindow, GameSelectWindow,
    WaitingWindow, GameWindow,
)
from .views.system.tutorial import TutorialWindow, TutorialPanel, _TOTAL as _TUT_TOTAL
from .views.system.docs import DocsWindow
from .views.system.settings import SettingsWindow
from .widgets.panel import PlayerSelected
from .widgets.which_key import WhichKeyPanel
from .config import NF_HOME, NF_BELL, NF_HEART, NF_ONLINE, NF_SWORD, DEFAULT_HOST

from .screen_modes import InputModeMixin
from .screen_overlay import OverlayMixin
from .screen_nav import NavigationMixin

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

# Shift+hjkl / uppercase WASD / Shift+arrows → 面板聚焦切换
_FOCUS_KEY = {
    'H': 'h', 'J': 'j', 'K': 'k', 'L': 'l',
    'W': 'k', 'A': 'h', 'S': 'j', 'D': 'l',
    'shift+left': 'h', 'shift+down': 'j', 'shift+up': 'k', 'shift+right': 'l',
}


class GameScreen(NavigationMixin, InputModeMixin, OverlayMixin, Screen):

    mode = reactive("tutorial")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.logged_in = False
        self.current_location = "lobby"
        self.state = ModuleStateManager()
        self._mode = 'normal'  # normal / insert / which_key / focus
        self._sticky_insert = False  # True = 大写 I，提交后不退出
        self._overlay_stack: list[str] = []  # 浮窗打开顺序 (widget id)

    def compose(self) -> ComposeResult:
        yield TutorialWindow(id="tutorial-window")
        yield LoginWindow(id="login-window")
        yield LobbyWindow(id="lobby-window")
        yield ChatWindow(id="chat-window")
        yield ProfileWindow(id="profile-window")
        yield OnlineWindow(id="online-window")
        yield NotificationWindow(id="notification-window")
        yield GameSelectWindow(id="game-select-window")
        yield WaitingWindow(id="waiting-window")
        yield GameWindow(id="game-window")
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
        from .storage import get_tutorial_done
        if not get_tutorial_done():
            self.mode = "tutorial"
            self.query_one("#tutorial-window").add_class("visible")
        else:
            self.mode = "login"
            self.query_one("#login-window").add_class("visible")
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
        if self.mode in ("login", "tutorial"):
            if self._mode != 'normal':
                self._to_normal()
            self.query_one("#login-window").remove_class("visible")
            self.query_one("#tutorial-window").hide()
            lobby = self.query_one("#lobby-window", LobbyWindow)
            lobby.add_class("visible")
            lobby.bind_state(self.state)
            self.state.game_board.add_listener(self._on_room_state_change)
            self.state.online.add_listener(self._on_online_event)
            self.mode = "game"

    async def _rebuild_to_login_layout(self):
        if self._mode != 'normal':
            self._to_normal()
        self._close_all_overlays()
        self.query_one("#lobby-window").remove_class("visible")
        self.query_one("#waiting-window").remove_class("visible")
        self.query_one("#game-window").remove_class("visible")
        self.query_one("#login-window").add_class("visible")
        # 重置所有 overlay window 的绑定状态，以便重新登录后能绑定新 State
        for wid in ("#chat-window", "#online-window", "#notification-window",
                    "#profile-window", "#game-select-window",
                    "#waiting-window", "#game-window"):
            try:
                w = self.query_one(wid)
                if hasattr(w, '_bound'):
                    w._bound = False
            except Exception:
                pass
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
        from .views.game.controls import RoomControlsPanel
        tabs = get_game_tabs()
        for rc in self.query(RoomControlsPanel):
            rc.update_commands(tabs)

    def _update_location(self, location: str, location_path: str | None = None):
        self.current_location = location
        self.state.status.update_location(location)
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
                self._close_game_select_overlay()
                self._close_all_overlays()
                self._switch_main_window('lobby')
            elif rs == 'waiting':
                self._close_game_select_overlay()
                self._close_all_overlays()
                self.state.chat.clear_room_messages()
                self._switch_main_window('waiting')
            elif rs in ('playing', 'finished'):
                self._close_all_overlays()
                self._switch_main_window('game')
        elif event == 'clear':
            self._switch_main_window('lobby')

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

        # NORMAL
        key = _KEY_ALIAS.get(event.key, event.key)

        if key == 'escape':
            if self._close_overlay():
                return
            if self.mode == 'tutorial':
                panel = self.query_one('#tutorial-panel')
                if panel._page == _TUT_TOTAL - 1:
                    panel.post_message(panel.TutorialDone())
                return
            w = self._get_active_window()
            if w and hasattr(w, 'nav'):
                w.nav('escape')
            return

        if key == 'space':
            if self.mode in ('login', 'tutorial'):
                return
            self._enter_which_key()
            return

        if key in ('i', 'I'):
            self._enter_insert(sticky=(key == 'I'))
            return

        # Shift+hjkl / WASD大写 / Shift+方向键 → 直接切换面板聚焦
        fk = _FOCUS_KEY.get(event.key)
        if fk:
            w = self._get_active_window()
            if w:
                w.focus_move(fk)
            return

        action = _KEY_ACTION.get(key)
        if action:
            w = self._get_active_window()
            if w and hasattr(w, 'nav'):
                w.nav(action)

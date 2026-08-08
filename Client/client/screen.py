"""
GameScreen — 主屏幕

职责拆分：
  screen_modes.py   — 文本输入模式状态机
  screen_nav.py     — 业务事件路由 (玩家选中 / DM / 教程 / 设置菜单)
  window_engine/    — 已注册窗口的统一生命周期管理
"""

from __future__ import annotations

from textual.screen import Screen
from textual.widgets import Static, Input
from textual.containers import Horizontal
from textual.app import ComposeResult
from textual.reactive import reactive
from textual import events

from .state import ModuleStateManager
# 触发所有窗口模块导入 → register_window() 自动注册窗口。
# screen.py 不再直接引用任何 Window 类。
from . import views as _views  # noqa: F401  (import-as-side-effect)
from .views.system.tutorial import TutorialPanel, _TOTAL as _TUT_TOTAL
from .widgets.panel import PlayerSelected
from .input_actions import (
    focus_direction, is_exit_key, is_popup_key, navigation_action,
    text_input_mode,
)
from .config import (
    NF_HOME, NF_BELL, NF_HEART, NF_COMPANION, NF_ONLINE, NF_SWORD,
    DEFAULT_HOST,
)

from .screen_modes import InputModeMixin
from .screen_nav import NavigationMixin

# 模块名 → widget ID
_MODULE_IDS = {
    'login': 'login-panel',
    'cmd': 'cmd-panel',
    'room_search': 'room-search',
    'game_detail': 'game-detail',
    'room_controls': 'room-controls',
}

class GameScreen(NavigationMixin, InputModeMixin, Screen):

    mode = reactive("tutorial")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.logged_in = False
        self.current_location = "lobby"
        self.state = ModuleStateManager()
        from .companion import CompanionController
        if CompanionController._instance is not None:
            CompanionController.instance(self.state)
        self._mode = 'normal'
        self._sticky_insert = False  # True = 大写 I，提交后不退出
        # 通用窗口引擎（所有已注册窗口均由引擎管理）
        from .window_engine import WindowEngine
        self.engine = WindowEngine()
        self.engine.attach(self, lambda: self)

    def compose(self) -> ComposeResult:
        # 全部窗口由引擎统一 compose
        yield from self.engine.compose_all()
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
            self.engine.set_primary("tutorial-window")
        else:
            self.mode = "login"
            self.engine.set_primary("login-window")
        self.app.connect_to_server(DEFAULT_HOST)

    # ── 模块访问（net/dispatch 调用）──

    def get_module(self, module_name: str):
        wid = _MODULE_IDS.get(module_name)
        if not wid:
            return None
        # room_controls 存在于多个窗口，优先从当前活跃窗口查找
        if module_name == 'room_controls':
            w = self.engine.active_window()
            if w:
                try:
                    return w.query_one(f"#{wid}")
                except Exception:
                    pass
        try:
            return self.query_one(f"#{wid}")
        except Exception:
            return None

    # ── 布局切换（net/dispatch 调用）──

    async def _rebuild_to_game_layout(self):
        if self.mode in ("login", "tutorial"):
            if self._mode != 'normal':
                self._to_normal()
            self.engine.set_primary("lobby-window")
            self.state.game_board.add_listener(self._on_room_state_change)
            self.state.online.add_listener(self._on_online_event)
            self.mode = "game"

    async def _rebuild_to_login_layout(self):
        if self._mode != 'normal':
            self._to_normal()
        self.engine.close_all()           # 关掉所有浮窗
        # 重置浮窗 + 主窗口的 _bound 标记, 以便重新登录后能绑定新 State
        for wid in ("chat-window", "online-window", "notification-window",
                    "profile-window", "chat-style-window", "game-select-window",
                    "waiting-window", "game-window", "lobby-window",
                    ):
            w = self.engine.get_window(wid)
            if w and hasattr(w, '_bound'):
                w._bound = False
        old_state = self.state
        old_state.unbind_all()
        old_state.game_interaction.reset()
        self.state = ModuleStateManager()
        from .companion import CompanionController
        if CompanionController._instance is not None:
            CompanionController.instance(self.state)
        self.engine.set_primary("login-window")
        login_window = self.engine.get_window("login-window")
        if login_window is not None:
            login_window.reset_session()
        self.mode = "login"

    # ── 徽章（net/dispatch 调用）──

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
        companion_unread = self.state.notify.companion_unread_count
        if companion_unread:
            parts.append(f"{NF_COMPANION} {companion_unread}")
        text = f" {' '.join(parts)} " if parts else ""
        badge.update(text)
        badge.refresh()

    def receive_companion_message(self, text: str) -> None:
        """Deliver a proactive companion reply on the Textual main thread."""
        window = self.engine.get_window("companion-window")
        active = self.engine.active_window()
        if window is not None:
            window.receive_proactive(text)
        if active is not window:
            self.state.notify.add_companion_unread()
        self.update_badges()

    # ── 位置/命令（net/dispatch 调用）──

    def _update_room_controls(self):
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
        """切换主窗口: 'lobby' / 'waiting' / 'game' — 转交给引擎"""
        self.engine.set_primary(f"{target}-window")

    def _on_room_state_change(self, event: str, *args) -> None:
        """监听 game_board state 变化, 自动切换主窗口"""
        if event == 'update_room':
            rd = args[0] if args else {}
            rs = rd.get('room_state', '')
            if rs == 'lobby':
                self.engine.close_all()
                self._switch_main_window('lobby')
            elif rs == 'waiting':
                self.engine.close_all()
                self.state.chat.clear_room_messages()
                self._switch_main_window('waiting')
            elif rs in ('playing', 'finished'):
                self.engine.close_all()
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
            if is_exit_key(event.key):
                event.prevent_default()
                event.stop()
                self._to_normal()
            return

        event.prevent_default()
        event.stop()

        # NORMAL
        if is_exit_key(event.key):
            if self.engine.close_top():
                return
            if self.mode == 'tutorial':
                panel = self.query_one('#tutorial-panel')
                if panel._page == _TUT_TOTAL - 1:
                    panel.post_message(panel.TutorialDone())
                return
            return

        if is_popup_key(event.key):
            if self.mode in ('login', 'tutorial'):
                return
            if self.engine.active_id() == "root-menu-window":
                self.engine.close_top()
            else:
                self.engine.open("root-menu-window")
            return

        sticky_input = text_input_mode(event.key)
        if sticky_input is not None:
            self._enter_insert(sticky=sticky_input)
            return

        fk = focus_direction(event.key)
        if fk:
            w = self.engine.active_window()
            if w:
                w.focus_move(fk)
            return

        action = navigation_action(event.key)
        if action:
            w = self.engine.active_window()
            if w and hasattr(w, 'nav'):
                w.nav(action)

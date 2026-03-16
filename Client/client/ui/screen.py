"""
GameScreen — NVim 风格动态窗口管理屏幕
"""

from __future__ import annotations

from textual.screen import Screen
from textual.widgets import Static
from textual.containers import Horizontal
from textual.binding import Binding
from textual.app import ComposeResult

from .vim_mode import VimMode, Mode
from ..protocol.handler import GameHandlerContext, get_handler
from ..state import ModuleStateManager
from .canvas import Canvas
from .layout import (
    PaneNode,
    get_default_layout, get_game_layout,
    serialize, deserialize,
    all_panes, find_pane, find_module_pane,
    split_pane, close_pane, resize_pane,
)
from ..panels import ChatPanel, CommandPanel, LoginPanel, AIChatPanel
from ..panels.inventory import InventoryPanel
from ..panels.online import OnlineUsersPanel
from ..panels.which_key import WhichKeyPanel
from .keyboard import KeyboardMixin
from .input_handler import InputMixin
from .space_menu import SpaceMenuMixin


class GameScreen(KeyboardMixin, InputMixin, SpaceMenuMixin, Screen):
    BINDINGS = [Binding("escape", "enter_normal", "", show=False)]

    def __init__(self, layout_data: dict | None = None, **kw):
        super().__init__(**kw)
        self.logged_in = False
        self.current_location = "lobby"
        self._input_buffer = ""
        self._focused_pane_id = ""
        self.state = ModuleStateManager()
        self._layout_loaded = False
        tree = None
        if layout_data:
            tree = deserialize(layout_data)
            self._layout_loaded = True
        if tree is None:
            tree = get_default_layout()
        self._layout_tree = tree

    def compose(self) -> ComposeResult:
        yield Canvas(self._layout_tree, id="canvas")
        yield WhichKeyPanel()
        with Horizontal(id="footer-bar"):
            yield Static(" NORMAL ", id="mode-indicator")
            yield Static("HOME", id="location-indicator")
            yield Static("----", id="connection-status")

    def on_mount(self) -> None:
        panes = all_panes(self._layout_tree)
        focus_id = ""
        for p in panes:
            if p.module in ('login', 'cmd'):
                focus_id = p.pane_id
                break
        if not focus_id and panes:
            focus_id = panes[0].pane_id
        if focus_id:
            self._set_focused_pane(focus_id)
        self._restore_all_modules()
        from ..config import DEFAULT_HOST
        self.app.connect_to_server(DEFAULT_HOST)
        self._enter_insert()

    async def _rebuild_to_game_layout(self):
        # 决定最终布局树
        saved = getattr(self.app, '_saved_layout', None)
        if saved:
            from .layout import deserialize
            tree = deserialize(saved)
            if tree:
                if self._layout_loaded:
                    # 已经用过保存布局，不再重复重建
                    return
                self._layout_tree = tree
                self._layout_loaded = True
        elif self._layout_loaded:
            # 已有保存布局，不降级为默认布局
            return
        else:
            self._layout_tree = get_game_layout()
        await self.canvas.rebuild(self._layout_tree)
        self._restore_all_modules()
        panes = all_panes(self._layout_tree)
        for p in panes:
            if p.module == 'cmd':
                self._set_focused_pane(p.pane_id)
                break
        else:
            if panes:
                self._set_focused_pane(panes[0].pane_id)
        self.action_enter_normal()

    # ── 画布与面板访问 ──

    @property
    def canvas(self) -> Canvas:
        return self.query_one("#canvas", Canvas)

    def _get_module(self, module_name: str):
        return self.canvas.get_module_widget(module_name)

    def _get_pane_for_module(self, module_name: str) -> PaneNode | None:
        return find_module_pane(self._layout_tree, module_name)

    @property
    def vim(self) -> VimMode:
        return self.app.vim

    # ── 焦点管理 ──

    def _set_focused_pane(self, pane_id: str):
        self._focused_pane_id = pane_id
        canvas = self.canvas
        for p in all_panes(self._layout_tree):
            wrapper = canvas.get_pane(p.pane_id)
            if wrapper:
                if p.pane_id == pane_id:
                    wrapper.add_class("--focused")
                    w = wrapper.module_widget
                    if w and hasattr(w, 'on_panel_focus'):
                        w.on_panel_focus()
                else:
                    wrapper.remove_class("--focused")

    def _focused_module(self) -> str | None:
        pane = find_pane(self._layout_tree, self._focused_pane_id)
        return pane.module if pane else None

    @property
    def _input_target(self) -> str:
        mod = self._focused_module()
        if mod in ('chat', 'cmd', 'login', 'inventory', 'ai', 'online'):
            return mod
        return ''

    def _can_input(self) -> bool:
        target = self._input_target
        if target in ('chat', 'cmd', 'login'):
            return True
        if target == 'inventory':
            w = self._get_module('inventory')
            return isinstance(w, InventoryPanel) and getattr(w, 'wants_insert', False)
        if target == 'ai':
            w = self._get_module('ai')
            if isinstance(w, AIChatPanel):
                if w.wants_insert:
                    return True
                return w._view == "chat" and w._menu_tab in ("chat", "action")
            return False
        if target == 'online':
            w = self._get_module('online')
            if isinstance(w, OnlineUsersPanel):
                if w.wants_insert:
                    return True
                return w._tab == "search"
            return False
        return False

    @property
    def _wk(self) -> WhichKeyPanel:
        return self.query_one(WhichKeyPanel)

    # ── 模式切换 ──

    def action_enter_normal(self):
        self._wk.close()
        if self.vim.mode == Mode.INSERT:
            self._input_buffer = ""
            self._hide_panel_prompt()
            self._hide_input_bar()
            w = self._get_focused_widget()
            if w and hasattr(w, 'cancel_input'):
                w.cancel_input()
            self.vim.enter_normal()
            self._update_mode_indicator()
            self.set_focus(None)
        else:
            # 已在 NORMAL 模式 — ESC 委派给聚焦面板的 nav_escape
            w = self._get_focused_widget()
            if w and hasattr(w, 'nav_escape'):
                w.nav_escape()

    def _enter_insert(self):
        if not self._can_input():
            return
        self._input_buffer = ""
        self.vim.enter_insert()
        # 指令面板: 输入的是 /cmd 英文指令，保持英文 IME
        if self._input_target == 'cmd':
            from . import ime
            ime.on_enter_normal()
        self._update_mode_indicator()
        # 搜索面板: 进入 INSERT 时标记 wants_insert
        w = self._get_focused_widget()
        if isinstance(w, OnlineUsersPanel):
            w._wants_insert = True
        self._show_panel_prompt("")
        self._show_input_bar()
        self.call_after_refresh(self._focus_active_input)

    def _focus_active_input(self):
        """聚焦当前面板的 InputTextArea"""
        from ..widgets.input_bar import InputTextArea
        mod = self._focused_module()
        widget = self._get_module(mod) if mod else None
        if widget:
            try:
                ta = widget.query_one(InputTextArea)
                ta.focus()
            except Exception:
                pass

    # ── InputTextArea 自定义消息 ──

    def on_text_area_changed(self, event) -> None:
        """TextArea 内容变更 — 同步 _input_buffer + 更新补全"""
        if self.vim.mode == Mode.INSERT:
            self._input_buffer = event.text_area.text
            self._update_completion()
            if self._input_target == 'online':
                w = self._get_module('online')
                if isinstance(w, OnlineUsersPanel):
                    w.on_search_change(self._input_buffer)
            elif self._input_target == 'inventory':
                w = self._get_module('inventory')
                if isinstance(w, InventoryPanel):
                    w.on_search_change(self._input_buffer)

    def on_input_text_area_submit(self, event) -> None:
        """Enter / Ctrl+Enter 提交"""
        if self.vim.mode == Mode.INSERT:
            self._handle_enter()

    def on_input_text_area_escape(self, event) -> None:
        """Escape 退出 INSERT"""
        self.action_enter_normal()

    def on_input_text_area_tab_press(self, event) -> None:
        """Tab 指令补全"""
        if self.vim.mode == Mode.INSERT:
            self._complete_command()

    def on_input_text_area_passthrough(self, event) -> None:
        """HJKL hint 导航"""
        if self.vim.mode == Mode.INSERT:
            nav_map = {"H": "left", "L": "right", "J": "down", "K": "up"}
            direction = nav_map.get(event.character)
            if direction:
                self._hint_nav(direction)

    def on_input_text_area_empty_backspace(self, event) -> None:
        """空文本 Backspace — 指令面板 hint_back"""
        if self.vim.mode == Mode.INSERT:
            self._hint_back()

    def on_ai_chat_panel_request_insert(self, event) -> None:
        """AI 面板异步步骤完成后请求进入 INSERT 模式"""
        self._enter_insert()

    def _update_mode_indicator(self):
        indicator = self.query_one("#mode-indicator", Static)
        mode = self.vim.mode
        if mode == Mode.NORMAL:
            indicator.update(" NORMAL ")
        elif mode == Mode.INSERT:
            indicator.update(" INSERT ")

    # ── 面板内输入提示 ──

    def _show_panel_prompt(self, text: str):
        mod = self._focused_module()
        widget = self._get_module(mod) if mod else None
        if isinstance(widget, (ChatPanel, CommandPanel, LoginPanel, InventoryPanel, AIChatPanel, OnlineUsersPanel)):
            widget.show_prompt(text)

    def _update_panel_prompt(self, text: str):
        mod = self._focused_module()
        widget = self._get_module(mod) if mod else None
        if isinstance(widget, (ChatPanel, CommandPanel, LoginPanel, InventoryPanel, AIChatPanel, OnlineUsersPanel)):
            widget.update_prompt(text)

    def _hide_panel_prompt(self):
        for mod in ('chat', 'cmd', 'login', 'inventory', 'ai', 'online'):
            widget = self._get_module(mod)
            if isinstance(widget, (ChatPanel, CommandPanel, LoginPanel, InventoryPanel, AIChatPanel, OnlineUsersPanel)):
                widget.hide_prompt()

    # ── Space 菜单由 SpaceMenuMixin 提供 ──

    async def _do_open_module(self, module_name: str):
        canvas = self.canvas
        # 如果该模块已在其他窗格中，先清除旧位置
        existing = find_module_pane(self._layout_tree, module_name)
        if existing and existing.pane_id != self._focused_pane_id:
            existing.module = None
        # 直接替换当前窗格的模块
        current = find_pane(self._layout_tree, self._focused_pane_id)
        if current:
            current.module = module_name
        await canvas.rebuild(self._layout_tree)
        self._restore_all_modules()
        self._set_focused_pane(self._focused_pane_id)
        self._save_layout()

    # ── 游戏模块切换 ──

    def _toggle_game_module(self, module_name: str):
        existing = find_module_pane(self._layout_tree, module_name)
        if existing:
            self._remove_module_panel(module_name)
        else:
            self._ensure_module_panel(module_name)

    def _toggle_all_game_modules(self, game_modules: list[str]):
        all_open = all(
            find_module_pane(self._layout_tree, m) is not None
            for m in game_modules)
        for m in game_modules:
            opened = find_module_pane(self._layout_tree, m) is not None
            if all_open and opened:
                self._remove_module_panel(m)
            elif not all_open and not opened:
                self._ensure_module_panel(m)

    def _restore_all_modules(self):
        for pane in all_panes(self._layout_tree):
            if pane.module:
                self._restore_module(pane.module)

    def _restore_module(self, module_name: str):
        widget = self._get_module(module_name)
        if not widget:
            return
        if hasattr(widget, 'restore'):
            widget.restore(self.state)

    # ── 布局操作 ──

    async def _do_split(self, direction: str):
        self._layout_tree = split_pane(self._layout_tree, self._focused_pane_id, direction)
        await self.canvas.rebuild(self._layout_tree)
        self._restore_all_modules()
        # 确保焦点窗格仍然有效
        panes = all_panes(self._layout_tree)
        ids = [p.pane_id for p in panes]
        if self._focused_pane_id not in ids and ids:
            self._focused_pane_id = ids[0]
        self._set_focused_pane(self._focused_pane_id)
        self._save_layout()

    async def _do_close_pane(self):
        panes = all_panes(self._layout_tree)
        if len(panes) <= 1:
            return
        ids = [p.pane_id for p in panes]
        idx = ids.index(self._focused_pane_id) if self._focused_pane_id in ids else 0
        next_id = ids[(idx + 1) % len(ids)] if len(ids) > 1 else ""
        if next_id == self._focused_pane_id:
            next_id = ids[(idx - 1) % len(ids)]
        result = close_pane(self._layout_tree, self._focused_pane_id)
        if result is None:
            return
        self._layout_tree = result
        await self.canvas.rebuild(self._layout_tree)
        self._restore_all_modules()
        # 确保焦点窗格仍然有效
        panes = all_panes(self._layout_tree)
        valid_ids = [p.pane_id for p in panes]
        if next_id not in valid_ids and valid_ids:
            next_id = valid_ids[0]
        if next_id:
            self._set_focused_pane(next_id)
        self._save_layout()

    def _resize_focused(self, delta: float, direction: str = 'h'):
        if resize_pane(self._layout_tree, self._focused_pane_id, delta, direction):
            self.canvas.sync_weights(self._layout_tree)
            self._save_layout()

    async def _do_refresh_panes(self):
        """重建所有窗格"""
        await self.canvas.rebuild(self._layout_tree)
        self._restore_all_modules()
        self._set_focused_pane(self._focused_pane_id)

    def _save_layout(self):
        if not self.logged_in:
            return
        layout_data = serialize(self._layout_tree)
        self.app.network.send({"type": "save_layout", "layout": layout_data})

    def _ensure_module_panel(self, module_name: str):
        existing = find_module_pane(self._layout_tree, module_name)
        if existing:
            return
        self._layout_tree = split_pane(self._layout_tree, self._focused_pane_id, 'h')
        for p in all_panes(self._layout_tree):
            if p.module is None:
                p.module = module_name
                break
        self.call_later(self._rebuild_and_restore)

    def _remove_module_panel(self, module_name: str):
        pane = find_module_pane(self._layout_tree, module_name)
        if not pane:
            return
        panes = all_panes(self._layout_tree)
        if len(panes) <= 1:
            return
        result = close_pane(self._layout_tree, pane.pane_id)
        if result is not None:
            self._layout_tree = result
            self.call_later(self._rebuild_and_restore)

    async def _rebuild_and_restore(self):
        await self.canvas.rebuild(self._layout_tree)
        self._restore_all_modules()
        self._set_focused_pane(self._focused_pane_id)
        self._save_layout()

    def _update_location(self, location: str, location_path: str | None = None):
        old_location = self.current_location
        self.current_location = location
        self.state.location = location

        old_game = old_location.split('_')[0] if old_location else ''
        new_game = location.split('_')[0] if location else ''
        game_changed = old_game != new_game

        if game_changed:
            if old_game:
                old_handler = get_handler(old_game)
                if old_handler:
                    ctx = GameHandlerContext(
                        self.state, self._get_module, self.app.set_timer,
                        self._ensure_module_panel, self._remove_module_panel)
                    old_handler.on_leave_game(ctx)
            new_handler = get_handler(new_game)
            if new_handler:
                ctx = GameHandlerContext(
                    self.state, self._get_module, self.app.set_timer,
                    self._ensure_module_panel, self._remove_module_panel)
                new_handler.on_enter_game(ctx)

        indicator = self.query_one("#location-indicator", Static)
        display = location_path or location
        indicator.update(display)

    # ── 键位处理由 KeyboardMixin 提供 ──
    # ── 输入处理由 InputMixin 提供 ──

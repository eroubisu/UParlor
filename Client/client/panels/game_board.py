"""GameBoardPanel — 通用游戏画面面板（委托 GameRenderer 渲染）"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static
from textual.widget import Widget
from textual.containers import Vertical, VerticalScroll

from ..config import M_DIM, M_END
from ..state import ModuleStateManager
from ..widgets import TabMenuBase, InputBar, InputBarMixin


class GameHintBar(TabMenuBase):
    """游戏指令菜单 — 纯菜单选择器，p/P 打开，HJKL 导航"""

    _tabs_widget_id = "game-hint-tabs"
    _content_widget_id = "game-hint-content"

    def compose(self) -> ComposeResult:
        yield Static("", id="game-hint-tabs", classes="hint-tabs")
        yield Static("", id="game-hint-content", classes="hint-content")

    def _item_name(self, item) -> str:
        if self._nav_stack:
            return item.label or item.command.lstrip('/')
        return item.command.lstrip('/')

    def _item_desc(self, item) -> str:
        return item.description or ""

    def _item_sub(self, item) -> list | None:
        return item.sub

    def _make_sub_tab(self, item) -> tuple[str, list]:
        return (item.label or item.command, item.sub)


class GameBoardPanel(InputBarMixin, Widget):
    """通用游戏面板：接收 room_data，查找对应 GameRenderer 渲染"""

    class RequestInsert(Message):
        """服务端推送选择菜单时请求进入 INSERT 模式"""

    _state_mgr = None
    _game_type: str = ''
    _input_bar_id = "game-input-bar"
    _scroll_target_id = ""
    _last_room_data: dict | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="game-board-toast")
        with VerticalScroll(id="game-board-scroll"):
            yield Static("", id="game-board-log")
        with Vertical(id="game-cmd-bar"):
            yield GameHintBar(id="game-hint-bar")
            yield InputBar(
                prompt_id="game-prompt",
                id="game-input-bar",
                submit_on_enter=True,
            )

    def on_mount(self) -> None:
        display = self.query_one("#game-board-log", Static)
        display.update(f"{M_DIM}暂无游戏画面{M_END}")

    def on_resize(self, event) -> None:
        self._send_viewport()
        if self._last_room_data:
            self._render_room(self._last_room_data)

    def _send_viewport(self) -> None:
        """Notify server of panel dimensions"""
        try:
            scroll = self.query_one("#game-board-scroll")
            region = scroll.content_region
            w, h = region.width, region.height
            if w > 0 and h > 0:
                self.app.network.send({"type": "viewport", "w": w, "h": h})
        except Exception:
            pass

    def _render_room(self, room_data: dict):
        from ..protocol.renderer import get_renderer
        try:
            display = self.query_one("#game-board-log", Static)
        except Exception:
            self._last_room_data = room_data
            return
        game_type = room_data.get('game_type', '')
        self._game_type = game_type
        self._last_room_data = room_data
        renderer = get_renderer(game_type)
        if renderer:
            state = room_data.get('state', 'waiting')
            if state == 'waiting' and hasattr(renderer, 'render_board_waiting'):
                content = renderer.render_board_waiting(room_data)
            else:
                content = renderer.render_board(room_data)
            display.update(content)
        else:
            display.update(f"[游戏面板] {game_type or '未知游戏'}")

    # ── 游戏指令菜单代理 ──

    def _hint_bar(self) -> GameHintBar | None:
        try:
            return self.query_one("#game-hint-bar", GameHintBar)
        except Exception:
            return None

    def update_game_tabs(self, tabs: list[tuple[str, list]]):
        bar = self._hint_bar()
        if bar:
            bar.update_tabs(tabs)

    def on_input_submit(self, text: str):
        handler, ctx = self._get_handler_ctx()
        if handler and ctx and hasattr(handler, 'on_nav_cancel'):
            handler.on_nav_cancel(ctx)
        if not text:
            return
        prefix = self._get_input_prefix()
        if prefix != '/':
            # 游戏输入模式: 一律走游戏前缀，指令只通过 hint bar 选择
            text = prefix + text
        self.app.send_command(text)

    def _get_input_prefix(self) -> str:
        """获取原始文本输入的指令前缀（游戏 handler 可自定义）"""
        if self._game_type:
            from ..protocol.handler import get_handler
            handler = get_handler(self._game_type)
            if handler:
                fn = getattr(handler, 'get_input_prefix', None)
                if fn:
                    location = self._state_mgr.location if self._state_mgr else ''
                    prefix = fn(location)
                    if prefix:
                        return prefix
        return '/'

    def show_hint_bar(self):
        """显示指令栏（c/C 打开）"""
        try:
            self.query_one("#game-hint-bar").add_class("visible")
        except Exception:
            pass

    def hide_hint_bar(self):
        """隐藏指令栏"""
        try:
            bar = self.query_one("#game-hint-bar", GameHintBar)
            bar.remove_class("visible")
            bar.reset_to_root()
        except Exception:
            pass

    def show_input_bar(self):
        """显示游戏输入框（i/I 打开）"""
        try:
            self.query_one("#game-input-bar").add_class("visible")
        except Exception:
            pass

    def hide_input_bar(self):
        """隐藏游戏输入框"""
        try:
            self.query_one("#game-input-bar").remove_class("visible")
        except Exception:
            pass

    # ── 通用选择菜单（推入 hint bar 子菜单）──

    def show_select_menu(self, title: str, items: list[dict], empty_msg: str = ''):
        """将选择菜单推入 hint bar 作为子菜单层级。

        items: [{'label': str, 'command': str}, ...]
        空列表时在子菜单中显示 empty_msg 提示。
        """
        bar = self._hint_bar()
        if not bar:
            return
        from ..protocol.commands import CommandInfo
        sub_items = [
            CommandInfo(command=it['command'], label=it['label'])
            for it in items
        ]
        bar._push_stack()
        if sub_items:
            bar._tabs = [(title, sub_items)]
        else:
            bar._tabs = [(empty_msg or title, [])]
        bar._active_tab = 0
        bar._selected_idx = 0
        bar._scroll_offset = 0
        bar._refresh_display()
        self.post_message(self.RequestInsert())

    # ── 导航（NORMAL 模式 j/k/h/l → 委托给游戏 Handler）──

    def _get_handler_ctx(self):
        """获取当前游戏 handler 和 context（缓存不必要，调用不频繁）"""
        if not self._game_type:
            return None, None
        from ..protocol.handler import get_handler, GameHandlerContext
        handler = get_handler(self._game_type)
        if not handler or not hasattr(handler, 'on_nav'):
            return handler, None
        ctx = GameHandlerContext(
            state=self._state_mgr,
            get_module=self.app.screen.get_module if hasattr(self.app, 'screen') else lambda n: None,
            set_timer=self.app.set_timer,
            send_command=self.app.send_command,
        )
        return handler, ctx

    def nav_down(self, count=1):
        handler, ctx = self._get_handler_ctx()
        if handler and ctx:
            handler.on_nav('down', count, ctx)

    def nav_up(self, count=1):
        handler, ctx = self._get_handler_ctx()
        if handler and ctx:
            handler.on_nav('up', count, ctx)

    def nav_tab_prev(self, count=1):
        handler, ctx = self._get_handler_ctx()
        if handler and ctx:
            handler.on_nav('left', count, ctx)

    def nav_tab_next(self, count=1):
        handler, ctx = self._get_handler_ctx()
        if handler and ctx:
            handler.on_nav('right', count, ctx)

    def nav_enter(self):
        handler, ctx = self._get_handler_ctx()
        if handler and ctx:
            handler.on_nav('enter', 1, ctx)

    def nav_back(self) -> bool:
        handler, ctx = self._get_handler_ctx()
        if handler and hasattr(handler, 'on_nav_cancel'):
            handler.on_nav_cancel(ctx)
        return False

    def nav_escape(self) -> bool:
        handler, ctx = self._get_handler_ctx()
        if handler and hasattr(handler, 'on_nav_cancel'):
            handler.on_nav_cancel(ctx)
        return False

    def show_toast(self, text: str):
        """在顶部消息栏显示最新一行（多行消息只显示最后一行）"""
        try:
            toast = self.query_one("#game-board-toast", Static)
            last_line = text.rstrip('\n').rsplit('\n', 1)[-1] if text else ''
            toast.update(last_line)
        except Exception:
            pass

    def _on_cmd_event(self, event: str, *args):
        """监听记录面板最新消息"""
        if event == 'add_line':
            text = args[0] if args else ''
            self.show_toast(text)

    def _on_state_event(self, event: str, *args):
        if event == 'update_room':
            (room_data,) = args
            self._render_room(room_data)
            # 通知游戏 Handler（如有 on_room_update 方法）
            handler, ctx = self._get_handler_ctx()
            if handler and hasattr(handler, 'on_room_update'):
                handler.on_room_update(room_data, ctx)
        elif event == 'clear':
            display = self.query_one("#game-board-log", Static)
            display.update("")

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        state.game_board.add_listener(self._on_state_event)
        state.cmd.add_listener(self._on_cmd_event)
        if state.game_board.room_data:
            self._render_room(state.game_board.room_data)
        # 恢复游戏指令菜单（可能在 _update_hint_bar 之后才挂载）
        from ..protocol.commands import get_game_tabs
        game_tabs = get_game_tabs()
        if game_tabs:
            self.update_game_tabs(game_tabs)

    def on_unmount(self):
        if self._state_mgr:
            self._state_mgr.game_board.remove_listener(self._on_state_event)
            self._state_mgr.cmd.remove_listener(self._on_cmd_event)

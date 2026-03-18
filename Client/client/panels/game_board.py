"""GameBoardPanel — 通用游戏画面面板（委托 GameRenderer 渲染）"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static
from textual.widget import Widget
from textual.containers import Vertical

from ..config import M_DIM, M_END
from ..state import ModuleStateManager
from ..widgets import TabMenuBase, InputBar, InputBarMixin


class GameHintBar(TabMenuBase):
    """游戏指令菜单 — 显示 scope='game' 的指令，始终可见"""

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

    _game_type: str = ''
    _input_bar_id = "game-input-bar"
    _scroll_target_id = ""
    _last_room_data: dict | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="game-board-toast")
        yield Static("", id="game-board-log")
        with Vertical(id="game-cmd-bar"):
            yield GameHintBar(id="game-hint-bar")
            yield InputBar(
                prompt_id="game-prompt",
                id="game-input-bar",
                submit_on_enter=True,
                passthrough_chars={"H", "J", "K", "L"},
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
            display = self.query_one("#game-board-log", Static)
            w, h = display.size.width, display.size.height
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
        if not text:
            return
        if not text.startswith("/"):
            text = "/" + text
        self.app.send_command(text)

    def show_input_bar(self):
        try:
            self.query_one("#game-cmd-bar").add_class("visible")
        except Exception:
            pass

    def hide_input_bar(self):
        try:
            self.query_one("#game-cmd-bar").remove_class("visible")
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

    # ── 导航（NORMAL 模式 j/k/h/l → 角色移动）──

    def nav_down(self, count=1):
        if self._game_type == 'world':
            self.app.send_command(f'/j {count}' if count > 1 else '/j')

    def nav_up(self, count=1):
        if self._game_type == 'world':
            self.app.send_command(f'/k {count}' if count > 1 else '/k')

    def nav_tab_prev(self, count=1):
        if self._game_type == 'world':
            self.app.send_command(f'/h {count}' if count > 1 else '/h')

    def nav_tab_next(self, count=1):
        if self._game_type == 'world':
            self.app.send_command(f'/l {count}' if count > 1 else '/l')

    def nav_enter(self):
        bar = self._hint_bar()
        if bar:
            item = bar.enter()
            if item:
                self.app.send_command(item.command)

    def nav_back(self) -> bool:
        bar = self._hint_bar()
        if bar:
            return bar.back()
        return False

    def nav_escape(self) -> bool:
        return False

    def show_toast(self, text: str):
        """在顶部消息栏显示一条消息（会被下一条覆盖）"""
        try:
            toast = self.query_one("#game-board-toast", Static)
            toast.update(text)
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
        elif event == 'clear':
            display = self.query_one("#game-board-log", Static)
            display.update("")

    def restore(self, state: ModuleStateManager):
        state.game_board.set_listener(self._on_state_event)
        state.cmd.set_listener(self._on_cmd_event)
        if state.game_board.room_data:
            self._render_room(state.game_board.room_data)
        # 恢复游戏指令菜单（可能在 _update_hint_bar 之后才挂载）
        from ..protocol.commands import get_game_tabs
        game_tabs = get_game_tabs()
        if game_tabs:
            self.update_game_tabs(game_tabs)

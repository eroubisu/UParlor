"""搜索房间面板 — 房间列表 + 搜索过滤"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static, Input
from textual.containers import VerticalScroll

from ...widgets.panel import Panel
from ...config import M_DIM, M_END, COLOR_FG_SECONDARY, ICON_INDENT


class RoomSearchPanel(Panel):
    """左侧房间搜索面板：input 搜索 + 房间列表"""

    class RoomSelected(Message):
        def __init__(self, room: dict) -> None:
            super().__init__()
            self.room = room

    icon_align = True
    follow_focus = True
    has_input = True
    title = "搜索房间"
    placeholder = "房间号或游戏名"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._rooms: list[dict] = []
        self._filtered: list[dict] = []
        self._query: str = ""

    def compose_content(self) -> ComposeResult:
        with VerticalScroll(classes="tab", id="t0"):
            yield Static(f"{ICON_INDENT}{M_DIM}暂无房间{M_END}", classes="content", markup=True)

    # ── 数据 ──

    def set_rooms(self, rooms: list[dict]) -> None:
        """设置房间列表: [{id, game, players, max_players, status}, ...]"""
        self._rooms = rooms
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self._query.lower()
        if q:
            self._filtered = [
                r for r in self._rooms
                if q in r.get('room_id', '').lower()
                or q in r.get('game_name', '').lower()
                or q in r.get('host', '').lower()
            ]
        else:
            self._filtered = list(self._rooms)
        self._cursor = min(self._cursor, max(0, len(self._filtered) - 1))
        self._render_list()
        self._notify_selection()

    def _render_list(self) -> None:
        if not self._filtered:
            self.update(f"{ICON_INDENT}{M_DIM}暂无房间{M_END}")
            return
        lines = []
        for i, r in enumerate(self._filtered):
            rid = r.get('room_id', '????')
            game = r.get('game_name', '???')
            icon = r.get('game_icon', '')
            cur = r.get('player_count', 0)
            mx = r.get('max_players', 0)
            state = r.get('state', '')
            state_label = {'waiting': '等待', 'playing': '进行中'}.get(state, state)
            prefix = "> " if i == self._cursor else ICON_INDENT
            label = f"{icon} " if icon else ''
            lines.append(f"{prefix}#{rid} {label}{game} {cur}/{mx} {state_label}")
        self._focus_line = self._cursor
        self.update("\n".join(lines))

    def get_selected_room(self) -> dict | None:
        if self._filtered and 0 <= self._cursor < len(self._filtered):
            return self._filtered[self._cursor]
        return None

    # ── 输入 ──

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._query = event.value.strip()
        self._apply_filter()
        event.stop()

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._query = ""
        self._render_list()

    # ── 导航 ──

    def nav(self, action: str) -> None:
        match action:
            case "up" | "down":
                if self._filtered and self._move_cursor(
                    -1 if action == 'up' else 1, len(self._filtered)
                ):
                    self._render_list()
                    self._notify_selection()
            case "enter":
                room = self.get_selected_room()
                if room:
                    self.app.network.send({"type": "join_room", "room_id": room['room_id']})
            case _:
                super().nav(action)

    def _notify_selection(self) -> None:
        """通知 LobbyWindow 选中房间变化"""
        room = self.get_selected_room()
        if room:
            self.post_message(self.RoomSelected(room))

    def bind_state(self, st) -> None:
        st.game_board.add_listener(self._on_board_event)

    def _on_board_event(self, event: str, data) -> None:
        if event == 'set_rooms':
            self.set_rooms(data)

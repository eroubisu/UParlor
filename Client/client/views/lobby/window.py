"""大厅窗口 — 记录 + 搜索房间 + 房间详情"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal

from ...widgets.window import Window
from .log import LogPanel
from .room_search import RoomSearchPanel
from .room_detail import RoomDetailPanel


class LobbyWindow(Window):
    """大厅窗口：顶部记录 + 下方左搜索右详情"""

    DEFAULT_CSS = """
    LobbyWindow {
        width: 1fr;
        height: 1fr;
    }
    LobbyWindow > #cmd-panel {
        dock: top;
        height: 3;
        width: 1fr;
        scrollbar-size: 0 0;
    }
    LobbyWindow > #lobby-body {
        height: 1fr;
        width: 1fr;
    }
    LobbyWindow > #lobby-body > #room-search {
        width: 2fr;
    }
    LobbyWindow > #lobby-body > #game-detail {
        width: 3fr;
    }
    """

    focus_grid = [["cmd-panel"], ["room-search", "game-detail"]]

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos = (1, 0)  # 默认聚焦搜索房间

    def compose(self) -> ComposeResult:
        yield LogPanel(id="cmd-panel")
        with Horizontal(id="lobby-body"):
            yield RoomSearchPanel(id="room-search")
            yield RoomDetailPanel(id="game-detail")

    def on_room_search_panel_room_selected(self, event) -> None:
        """搜索面板选中房间变化 → 更新详情面板"""
        detail = self.query_one("#game-detail", RoomDetailPanel)
        detail.show_room(event.room)

    def bind_state(self, st) -> None:
        self.query_one("#cmd-panel", LogPanel).bind_state(st)
        self.query_one("#room-search", RoomSearchPanel).bind_state(st)
        self.query_one("#game-detail", RoomDetailPanel).bind_state(st)

    def show(self) -> None:
        self.query_one("#game-detail", RoomDetailPanel).show_room(None)
        super().show()

"""等候室窗口 — LogPanel + 左侧房间信息/玩家列表/操作 + 右侧聊天"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

from ...widgets.window import Window
from ...window_engine import WindowSpec, register_window
from ...window_specs import bind_state_with_send
from ..lobby.log import LogPanel
from .info import RoomInfoPanel
from .player_list import PlayerListPanel
from .controls import RoomControlsPanel
from ..chat.content import ChatContentPanel


class WaitingWindow(Window):
    """等候室主窗口"""

    DEFAULT_CSS = """
    WaitingWindow {
        width: 1fr;
        height: 1fr;
    }
    WaitingWindow > #wait-log {
        dock: top;
        height: 3;
        width: 1fr;
        scrollbar-size: 0 0;
    }
    WaitingWindow > #wait-body {
        height: 1fr;
        width: 1fr;
    }
    WaitingWindow > #wait-body > #wait-left {
        width: 1fr;
    }
    WaitingWindow > #wait-body > #wait-left > #room-info {
        height: auto;
        max-height: 8;
    }
    WaitingWindow > #wait-body > #wait-left > #player-list {
        height: 1fr;
    }
    WaitingWindow > #wait-body > #wait-left > #room-controls {
        height: auto;
        max-height: 10;
    }
    WaitingWindow > #wait-body > #wait-chat {
        width: 2fr;
    }
    """

    focus_grid = [
        ["wait-log"],
        ["room-info", "wait-chat"],
        ["player-list", "wait-chat"],
        ["room-controls", "wait-chat"],
    ]

    # WindowEngine 主窗口 (等候室)
    spec = WindowSpec(
        id="waiting-window", title="等候室",
        group="primary", mode="primary", order=30,
        bind=bind_state_with_send,
    )

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos = (3, 0)  # 默认聚焦操作面板
        self._bound = False
        self._send_fn = None

    def compose(self) -> ComposeResult:
        yield LogPanel(id="wait-log")
        with Horizontal(id="wait-body"):
            with Vertical(id="wait-left"):
                yield RoomInfoPanel(id="room-info")
                yield PlayerListPanel(id="player-list")
                yield RoomControlsPanel(id="room-controls")
            yield ChatContentPanel(id="wait-chat")

    def bind_state(self, st, send_fn=None) -> None:
        if self._bound:
            return
        self._bound = True
        self._send_fn = send_fn
        self.query_one("#wait-log", LogPanel).bind_state(st)
        self.query_one("#room-info", RoomInfoPanel).bind_state(st)
        self.query_one("#player-list", PlayerListPanel).bind_state(st)
        rc = self.query_one("#room-controls", RoomControlsPanel)
        if send_fn:
            rc.bind_send(send_fn)
        cp = self.query_one("#wait-chat", ChatContentPanel)
        cp.bind_state(st)
        cp.show_conversation("room")

    def update_commands(self, tabs) -> None:
        """刷新房间操作列表"""
        self.query_one("#room-controls", RoomControlsPanel).update_commands(tabs)


register_window(WaitingWindow)

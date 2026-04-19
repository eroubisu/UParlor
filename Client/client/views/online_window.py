"""在线玩家浮动窗口 — 左侧列表 + 右侧名片详情"""

from __future__ import annotations

from textual.app import ComposeResult

from ..widgets.window import Window
from .online_list import OnlineListPanel
from .status_panel import StatusPanel


class OnlineWindow(Window):
    """浮动在线玩家窗口"""

    DEFAULT_CSS = """
    OnlineWindow {
        layer: floating;
        width: 62%;
        height: 62%;
    }
    OnlineWindow > #online-list {
        width: 30;
        height: 1fr;
    }
    OnlineWindow > #online-detail {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["online-list", "online-detail"]]
    primary_panel = "online-list"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos = (0, 0)
        self._bound = False
        self._online_state = None
        self._state = None

    def compose(self) -> ComposeResult:
        yield OnlineListPanel(id="online-list")
        yield StatusPanel(id="online-detail")

    def bind_state(self, st) -> None:
        if self._bound:
            return
        self._bound = True
        self._state = st
        self._online_state = st.online
        st.online.add_listener(self._on_online_event)
        self.query_one("#online-list", OnlineListPanel).bind_state(st)

    def _on_online_event(self, event: str, *args):
        if event == 'viewed_card':
            detail = self.query_one("#online-detail", StatusPanel)
            data = args[0]
            my_name = self._state.status.player_data.get('name', '') if self._state else ''
            friends = (self._state.online.friends or []) if self._state else []
            detail.render_card(data, is_self=(data.get('name') == my_name),
                               friends=friends)

    def show(self) -> None:
        super().show()

    def on_player_selected(self, event: PlayerSelected) -> None:
        """左侧选中玩家 → 请求名片"""
        event.stop()
        self.app.network.send({"type": "get_profile_card", "target": event.name})

    def nav(self, action: str) -> None:
        super().nav(action)
        # 左侧列表 Enter → 聚焦右侧详情
        if action == "enter" and self._focus_pos == (0, 0):
            self.focus_move('l')

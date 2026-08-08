"""在线玩家浮动窗口 — 左侧列表 + 右侧名片详情"""

from __future__ import annotations

from textual.app import ComposeResult

from ...widgets.panel import PlayerSelected
from ...widgets.window import Window
from ...window_engine import WindowSpec, register_window
from ...window_specs import logged_in, bind_state
from .online_list import OnlineListPanel
from .status_panel import StatusPanel

_INITIAL_CARD_TIMEOUT = 0.5


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
    presentation_timeout = _INITIAL_CARD_TIMEOUT

    spec = WindowSpec(
        id="online-window", title="在线", menu=True, group="root", order=20,
        preconditions=(logged_in,),
        bind=bind_state,
    )

    def __init__(self, **kw):
        super().__init__(**kw)
        self._focus_pos = (0, 0)
        self._bound = False
        self._state = None
        self._initial_card_ready = False

    def compose(self) -> ComposeResult:
        yield OnlineListPanel(id="online-list")
        yield StatusPanel(id="online-detail")

    def bind_state(self, st) -> None:
        if self._bound:
            return
        self._bound = True
        self._state = st
        st.online.add_listener(self._on_online_event)
        self.query_one("#online-list", OnlineListPanel).bind_state(st)

    def _on_online_event(self, event: str, *args):
        if event == 'viewed_card':
            player_list = self.query_one("#online-list", OnlineListPanel)
            detail = self.query_one("#online-detail", StatusPanel)
            data = args[0]
            selected = player_list.selected_option
            if selected is None or data.get('name') != selected.id:
                return
            my_name = self._state.status.player_data.get('name', '') if self._state else ''
            friends = (self._state.online.friends or []) if self._state else []
            detail.render_card(data, is_self=(data.get('name') == my_name),
                               friends=friends)
            self._initial_card_ready = True
            self.resume_presentation()

    def prepare_presentation(self) -> None:
        self._initial_card_ready = False

    def on_presentation_timeout(self) -> None:
        self.query_one("#online-detail", StatusPanel).render_card(None)
        self._initial_card_ready = True

    def presentation_ready(self) -> bool:
        selected = self.query_one(
            "#online-list", OnlineListPanel,
        ).selected_option
        return selected is None or self._initial_card_ready

    def on_player_selected(self, event: PlayerSelected) -> None:
        """左侧选中玩家 → 请求名片"""
        event.stop()
        self.app.network.send({"type": "get_profile_card", "target": event.name})

    def nav(self, action: str) -> None:
        super().nav(action)
        # 左侧列表 Enter → 聚焦右侧详情
        if action == "enter" and self._focus_pos == (0, 0):
            self.focus_move('l')


register_window(OnlineWindow)

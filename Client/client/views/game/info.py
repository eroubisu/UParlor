"""房间信息面板 — 显示房间号、游戏类型、房主等"""

from __future__ import annotations

from ...config import M_BOLD, M_DIM, M_END, M_MUTED
from ...widgets.panel import Panel


class RoomInfoPanel(Panel):
    """等候室房间信息面板"""

    title = "房间"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._game_state = None

    def bind_state(self, st) -> None:
        self._game_state = st.game_board
        st.game_board.add_listener(self._on_event)
        self._refresh()

    def _on_event(self, event: str, *args):
        if event in ('update_room', 'clear'):
            self._refresh()

    def _refresh(self) -> None:
        rd = self._game_state.room_data if self._game_state else {}
        if not rd:
            self.update(f"{M_DIM}未加入房间{M_END}")
            return
        rid = rd.get('room_id', '????')
        game = rd.get('game_type', '???')
        host = rd.get('host', '')
        state = rd.get('room_state', '')
        players = rd.get('players', [])
        count = len(players) if isinstance(players, list) else rd.get('player_count', 0)
        max_p = rd.get('max_players', 0)

        self.border_title = f"#{rid}"
        lines = [
            f"游戏    {M_BOLD}{game}{M_END}",
            f"房主    {host}",
            f"人数    {count}/{max_p}" if max_p else f"人数    {count}",
            f"状态    {state}",
        ]
        self.update("\n".join(lines))

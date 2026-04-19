"""房间详情面板 — 显示选中房间的详细信息"""

from __future__ import annotations

from ..widgets.panel import Panel
from ..config import M_DIM, M_BOLD, M_END


class RoomDetailPanel(Panel):
    """右侧房间详情面板：选中房间后显示详情"""

    title = "房间详情"

    def show_room(self, room: dict | None) -> None:
        """显示指定房间的详情"""
        if not room:
            self.update(f"{M_DIM}选择一个房间查看详情{M_END}")
            return
        rid = room.get('room_id', '????')
        game = room.get('game_name', '???')
        icon = room.get('game_icon', '')
        cur = room.get('player_count', 0)
        mx = room.get('max_players', 0)
        host = room.get('host', '')
        state = room.get('state', '')
        state_label = {'waiting': '等待', 'playing': '进行中'}.get(state, state)

        label = f"{icon} {game}" if icon else game
        lines = [
            f"{M_BOLD}#{rid} {label}{M_END}",
            "",
            f"房主    {host}",
            f"人数    {cur}/{mx}",
            f"状态    {state_label}",
        ]
        self.update("\n".join(lines))

    def bind_state(self, st) -> None:
        pass

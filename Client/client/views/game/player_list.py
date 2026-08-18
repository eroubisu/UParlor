"""玩家列表面板 — 显示房间内玩家"""

from __future__ import annotations
from rich.markup import escape

from ...config import (
    COLOR_FG_PRIMARY, COLOR_HINT_TAB_DIM, ICON_INDENT,
    M_DIM, M_END, NF_OFFLINE, NF_ONLINE,
)
from ...widgets.panel import Panel, PlayerSelected
from ...window_engine import Option, SurfaceState


class PlayerListPanel(Panel):
    """等候室/游戏内玩家列表"""

    icon_align = True
    follow_focus = True
    title = "玩家"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._game_state = None

    def bind_state(self, st) -> None:
        self._game_state = st.game_board
        st.game_board.add_listener(self._on_event)
        self._refresh_list()

    def _on_event(self, event: str, *args):
        if event in ('update_room', 'clear'):
            self._refresh_list()

    def _get_players(self) -> list[str]:
        if not self._game_state or not self._game_state.room_data:
            return []
        rd = self._game_state.room_data
        return rd.get('players', rd.get('player_names', []))

    def _refresh_list(self) -> None:
        players = self._get_players()
        rd = self._game_state.room_data if self._game_state else {}
        host = rd.get('host', '')
        max_p = rd.get('max_players', 0)
        ready = set(rd.get('ready') or [])
        bots = set(rd.get('bots') or [])
        if max_p:
            self.border_title = f"玩家 ({len(players)}/{max_p})"
        elif players:
            self.border_title = f"玩家 ({len(players)})"
        else:
            self.border_title = "玩家"
        lines: list[str] = []
        if not players:
            self.show_surface(SurfaceState.empty("暂无玩家"))
            return
        else:
            options = []
            for name in players:
                if name == host:
                    dot = f"[#d4a017]{NF_ONLINE}[/]"
                elif name in ready or name in bots:
                    dot = f"[#81c784]{NF_ONLINE}[/]"
                else:
                    dot = f"[#ffffff]{NF_OFFLINE}[/]"
                options.append(Option(
                    name, f"{dot} {escape(name)}", markup=True,
                ))
            self.set_options(options, "room-players")
            lines.append(self.render_options())
        self._focus_line = self.selected_line()
        self.update("\n".join(lines))

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._refresh_list()

    def reflow_content(self) -> None:
        self._refresh_list()

    def nav(self, action: str) -> None:
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self._refresh_list()
        elif selected is not None:
            self.post_message(PlayerSelected(selected.id))
        else:
            super().nav(action)

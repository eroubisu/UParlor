"""玩家列表面板 — 显示房间内玩家"""

from __future__ import annotations

from ..config import (
    COLOR_FG_PRIMARY, COLOR_FG_TERTIARY, COLOR_HINT_TAB_DIM, ICON_INDENT,
    M_DIM, M_END,
)
from ..widgets.panel import Panel, PlayerSelected


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
        if max_p:
            self.border_title = f"玩家 ({len(players)}/{max_p})"
        elif players:
            self.border_title = f"玩家 ({len(players)})"
        else:
            self.border_title = "玩家"
        lines: list[str] = []
        if not players:
            lines.append(f"{ICON_INDENT}{M_DIM}暂无玩家{M_END}")
        else:
            self._cursor = min(self._cursor, len(players) - 1)
            for i, name in enumerate(players):
                tag = f" [{COLOR_FG_TERTIARY}]\\[房主][/]" if name == host else ""
                if i == self._cursor:
                    lines.append(f"[bold {COLOR_FG_PRIMARY}]> {name}{tag}[/]")
                else:
                    lines.append(f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{name}{tag}[/]")
        self._focus_line = self._cursor
        self.update("\n".join(lines))

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._refresh_list()

    def nav(self, action: str) -> None:
        players = self._get_players()
        if not self._cursor_nav(
            action, len(players),
            on_enter=lambda: self.post_message(PlayerSelected(players[self._cursor])) if players else None,
            redraw=self._refresh_list,
        ):
            super().nav(action)

"""游戏列表面板 — 左侧选择游戏"""

from __future__ import annotations

from textual.message import Message

from ...config import (
    COLOR_FG_PRIMARY, COLOR_HINT_TAB_DIM, ICON_INDENT,
    M_DIM, M_END,
)
from ...widgets.panel import Panel


class GameSelected(Message):
    """用户选中某个游戏"""
    def __init__(self, game: dict) -> None:
        super().__init__()
        self.game = game


class FocusRight(Message):
    """请求聚焦右侧面板"""


class GameListPanel(Panel):
    """游戏列表面板：光标导航选择游戏"""

    icon_align = True
    title = "游戏"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._game_state = None

    def bind_state(self, st) -> None:
        self._game_state = st.game_board
        st.game_board.add_listener(self._on_event)
        self._refresh_list()

    def _on_event(self, event: str, *args):
        if event == 'set_games':
            self._refresh_list()

    def _get_items(self) -> list[dict]:
        if not self._game_state:
            return []
        return self._game_state.games

    def _refresh_list(self) -> None:
        items = self._get_items()
        lines: list[str] = []
        if not items:
            lines.append(f"{ICON_INDENT}{M_DIM}暂无可用游戏{M_END}")
        else:
            self._cursor = min(self._cursor, len(items) - 1)
            for i, g in enumerate(items):
                icon = g.get('icon', '>')
                name = g.get('name', g.get('id', '???'))
                if i == self._cursor:
                    lines.append(f"{icon} [bold {COLOR_FG_PRIMARY}]{name}[/]")
                else:
                    lines.append(f"[{COLOR_HINT_TAB_DIM}]{icon} {name}[/]")
        self._focus_line = self._cursor
        self.update("\n".join(lines))
        self._emit_selected()

    def _emit_selected(self) -> None:
        items = self._get_items()
        if items and 0 <= self._cursor < len(items):
            self.post_message(GameSelected(items[self._cursor]))

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._refresh_list()

    def nav(self, action: str) -> None:
        if not self._cursor_nav(
            action, len(self._get_items()),
            on_enter=lambda: self.post_message(FocusRight()),
            redraw=self._refresh_list,
        ):
            super().nav(action)

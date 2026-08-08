"""游戏列表面板 — 左侧选择游戏"""

from __future__ import annotations

from textual.message import Message
from rich.markup import escape

from ...config import (
    COLOR_FG_PRIMARY, COLOR_HINT_TAB_DIM, ICON_INDENT,
    M_DIM, M_END,
)
from ...widgets.panel import Panel
from ...protocol.renderer import get_renderer
from ...window_engine import Option, SurfaceState


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
    follow_focus = True
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
            self.show_surface(SurfaceState.empty("暂无可用游戏"))
            return
        else:
            options = []
            for g in items:
                game_id = g.get('id', '')
                renderer = get_renderer(game_id)
                icon = renderer.icon if renderer else ''
                name = g.get('name', game_id or '???')
                options.append(Option(
                    game_id,
                    f"{icon} {escape(name)}".strip(),
                    data=g,
                    markup=True,
                ))
            self.set_options(options, "game-list")
            lines.append(self.render_options())
        self._focus_line = self.selected_line()
        self.update("\n".join(lines))
        self._emit_selected()

    def _emit_selected(self) -> None:
        selected = self.selected_option
        if selected is not None:
            self.post_message(GameSelected(selected.data))

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._refresh_list()

    def reflow_content(self) -> None:
        items = self._get_items()
        if items:
            self.update(self.render_options())

    def nav(self, action: str) -> None:
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self._refresh_list()
        elif selected is not None:
            self.post_message(FocusRight())
        else:
            super().nav(action)

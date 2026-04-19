"""游戏棋盘面板 — 3 分区架构（info / board / controls）

布局：
  Static#board-info       ← 固定顶部 (height: auto)
  VerticalScroll.tab#t0   ← 中间可滚动 (height: 1fr)
    Static.content#board-main
  Static#board-controls   ← 固定底部 (height: auto)
"""

from __future__ import annotations

from textual.widgets import Static
from textual.containers import VerticalScroll
from textual.app import ComposeResult

from ..config import M_DIM, M_END, COLOR_BORDER
from ..widgets.panel import Panel, _widget_width, _widget_height
from ..protocol.renderer import get_renderer, render_doc
from ..protocol.handler import get_handler, GameHandlerContext

# 卡牌布局常量（需与 renderer 中的 _CARD_W 一致）
_CARD_TOTAL_W = 5  # 内宽3 + 左右边框2
_CARD_GAP = 1      # 牌间距


def _calc_cards_per_row(board_width: int) -> int:
    """根据面板宽度计算每行可容纳的牌数"""
    usable = board_width - 2  # 减去手动缩进 '  '
    return max(1, (usable + _CARD_GAP) // (_CARD_TOTAL_W + _CARD_GAP))


def _sig(content) -> str:
    """计算内容签名用于脏检查"""
    from rich.text import Text
    if content is None:
        return ''
    if isinstance(content, Text):
        return content.plain + repr(content._spans)
    return str(content)


class GameBoardPanel(Panel):
    """游戏棋盘渲染面板 — 3 分区"""

    title = "游戏"
    full_width_content = True
    hide_scrollbar = True
    follow_focus = True

    DEFAULT_CSS = f"""
    GameBoardPanel {{
        layout: vertical;
    }}
    GameBoardPanel > #board-info {{
        height: auto;
        padding: 0;
    }}
    GameBoardPanel > .tab {{
        height: 1fr;
    }}
    GameBoardPanel > #board-controls {{
        height: auto;
        padding: 0;
        border-top: solid {COLOR_BORDER};
    }}
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self._state = None
        self._game_state = None
        self._send_command = None
        self._set_timer = None
        self._section_sigs: dict[str, str] = {}
        self._showing_doc = False

    def compose_content(self) -> ComposeResult:
        yield Static("", id="board-info", classes="full-width", markup=True)
        with VerticalScroll(classes="tab", id="t0"):
            yield Static("", id="board-main", classes="content full-width", markup=True)
        yield Static("", id="board-controls", classes="full-width", markup=True)

    def bind_state(self, st, send_command=None, set_timer=None) -> None:
        self._state = st
        self._game_state = st.game_board
        self._send_command = send_command
        self._set_timer = set_timer
        st.game_board.add_listener(self._on_event)
        self._refresh()

    def _on_event(self, event: str, *args):
        if event in ('update_room', 'clear'):
            if event == 'clear':
                self._section_sigs.clear()
            self._refresh()

    def on_resize(self, event) -> None:
        self._section_sigs.clear()
        self._refresh()

    def _make_ctx(self) -> GameHandlerContext | None:
        if not self._state:
            return None
        try:
            screen = self.screen
        except Exception:
            return None
        return GameHandlerContext(
            state=self._state,
            get_module=screen.get_module,
            set_timer=self._set_timer,
            send_command=self._send_command,
        )

    def _refresh(self) -> None:
        if self._showing_doc:
            return
        rd = self._game_state.room_data if self._game_state else {}
        if not rd:
            self._update_section('board-info', None)
            self._update_section('board-main', f"{M_DIM}等待游戏数据…{M_END}")
            self._update_section('board-controls', None)
            return
        game_type = rd.get('game_type', '')
        room_state = rd.get('room_state', '')
        renderer = get_renderer(game_type) if game_type else None
        if not renderer:
            self._update_section('board-info', None)
            self._update_section('board-main', f"{M_DIM}未知游戏类型: {game_type}{M_END}")
            self._update_section('board-controls', None)
            return

        board_width = _widget_width(self, 't0')
        board_height = _widget_height(self, 't0')

        handler = get_handler(game_type)
        interaction = None
        if handler and hasattr(handler, 'interaction_state') and room_state == 'playing':
            interaction = handler.interaction_state
            if hasattr(handler, '_cards_per_row'):
                handler._cards_per_row = _calc_cards_per_row(board_width)

        sections = renderer.render_board(rd, interaction, board_width, board_height)

        self._update_section('board-info', sections.get('info'))
        self._update_section('board-main', sections.get('board'))
        self._update_section('board-controls', sections.get('controls'))

        hint = getattr(renderer, 'scroll_hint', -1)
        if hint >= 0:
            self.scroll_to_line(hint)

        self.border_title = game_type

    def _update_section(self, widget_id: str, content) -> None:
        """对比签名，只在内容变化时 update 对应 Static"""
        sig = _sig(content)
        if sig == self._section_sigs.get(widget_id):
            return
        self._section_sigs[widget_id] = sig
        try:
            widget = self.query_one(f"#{widget_id}", Static)
        except Exception:
            return
        if content is None:
            widget.update("")
            widget.display = False
        else:
            widget.display = True
            widget.update(content)

    def show_doc(self, renderable) -> None:
        from textual.containers import VerticalScroll
        self._showing_doc = True
        self._section_sigs.clear()
        self.border_title = "帮助"
        try:
            self.query_one("#board-info", Static).display = False
            self.query_one("#board-controls", Static).display = False
        except Exception:
            pass
        try:
            vs = self.query_one("#t0", VerticalScroll)
            vs.styles.scrollbar_size_vertical = 1
        except Exception:
            pass
        self.query_one("#board-main", Static).update(renderable)
        try:
            vs = self.query_one("#t0", VerticalScroll)
            self.call_after_refresh(vs.scroll_home, animate=False)
        except Exception:
            pass

    def close_doc(self) -> None:
        if not self._showing_doc:
            return
        self._showing_doc = False
        self._section_sigs.clear()
        from textual.containers import VerticalScroll
        try:
            self.query_one("#board-info", Static).display = True
            self.query_one("#board-controls", Static).display = True
        except Exception:
            pass
        try:
            vs = self.query_one("#t0", VerticalScroll)
            vs.styles.scrollbar_size_vertical = 0
        except Exception:
            pass
        self._refresh()

    def nav(self, action: str) -> None:
        if self._showing_doc:
            super().nav(action)
            return
        rd = self._game_state.room_data if self._game_state else {}
        game_type = rd.get('game_type', '')
        room_state = rd.get('room_state', '')
        handler = get_handler(game_type) if game_type else None

        if (handler and hasattr(handler, 'on_nav')
                and room_state == 'playing'
                and hasattr(handler, 'interaction_state')
                and handler.interaction_state is not None):
            ctx = self._make_ctx()
            if ctx:
                direction_map = {
                    'up': 'up', 'down': 'down',
                    'tab_prev': 'left', 'tab_next': 'right',
                    'enter': 'enter',
                }
                direction = direction_map.get(action)
                if direction:
                    handler.on_nav(direction, ctx)
                    return
        super().nav(action)

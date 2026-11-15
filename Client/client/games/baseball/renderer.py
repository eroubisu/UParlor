"""棒球渲染器 — 棋盘只画图形，文字状态全在右栏标签页，操作区在棋盘下方。

棋盘（图形，尺寸跟着棋盘区走，最小 88×32 也放得下）：内野正方形（`diamond.Infield`）
加三条固定行（投打 / 外野 / 传球，`diamond.ProgressTrack` 的三个子类）。
右栏是三页状态（`status`），棋盘下方是操作区（`panel`），设置项与按钮只写「标签 + 数据」。
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from ...config import (
    NF_ARROW_D, NF_ARROW_L, NF_ARROW_R, NF_ARROW_U, NF_BULLSEYE, NF_CARET_D,
    NF_CARET_U, NF_CIRCLE_NOTCH, NF_CROSS, NF_HIT_FLAT, NF_HIT_HIGH,
    NF_HIT_LOW, NF_LEVEL, NF_OFFLINE, NF_ONLINE, NF_USER,
)
from ...protocol.renderer import GameStatusContent, register_renderer, render_doc
from .diamond import GUIDE_GLYPH, Infield, track_rows
from .panel import render_controls
from .status import STATUS_HEIGHT, status_content
from .view import Board

_DOC_COMMANDS = {
    'create', 'rooms', 'start', 'invite', 'kick', 'bot', 'shift', 'pitch',
    'swing', 'hit', 'field', 'catch', 'run', 'throw', 'hold', 'forfeit',
    'back', 'help',
}


class BaseballRenderer:
    """棒球渲染器。"""

    game_type = 'baseball'
    icon = NF_BULLSEYE
    controls_height = 8     # 操作区固定 8 行：标题 1 行 + 内容 7 行，换菜单不让棋盘长高变矮
    glyphs = frozenset({
        NF_ARROW_D, NF_ARROW_L, NF_ARROW_R, NF_ARROW_U, NF_BULLSEYE,
        NF_CARET_D, NF_CARET_U, NF_CIRCLE_NOTCH, NF_CROSS, NF_HIT_FLAT,
        NF_HIT_HIGH, NF_HIT_LOW, NF_LEVEL, NF_OFFLINE, NF_ONLINE,
        NF_USER,
        '█', '─', '│', '·', GUIDE_GLYPH,
    })
    scroll_hint: int = -1
    doc_commands = _DOC_COMMANDS

    def __init__(self) -> None:
        self._parsed: tuple[dict, Board] | None = None

    def _board(self, room_data: dict) -> Board | None:
        """棋盘数据只在比赛进行 / 结束后才有；同一份数据只解析一次。"""
        if room_data.get('room_state') not in ('playing', 'finished'):
            return None
        if self._parsed is None or self._parsed[0] is not room_data:
            self._parsed = (room_data, Board.parse(room_data))
        return self._parsed[1]

    def status_height(self, room_data: dict) -> int:
        """固定高度：面板不随局面长高变矮，聊天区的位置也不会跳。"""
        return STATUS_HEIGHT

    def render_status(self, room_data: dict,
                      interaction: dict | None = None) -> GameStatusContent:
        board = self._board(room_data)
        return status_content(board) if board else GameStatusContent(None)

    def render_board(self, room_data: dict, interaction: dict | None = None,
                     board_width: int = 80, board_height: int = 30,
                     ) -> dict[str, RenderableType | None]:
        board = self._board(room_data)
        if board is None:
            doc = room_data.get('doc')
            return {'board': (render_doc(doc, _DOC_COMMANDS) if doc
                              else Text('')),
                    'controls': None}
        ui = interaction['ui'] if interaction else None
        # 自己刚按下击球时，ui 里的棋盘带着「已挥棒」：回执到之前画它而不是原始数据
        board = ui.board if ui and ui.pressed else board
        anim = ui.anim if ui else None
        text = Text()
        rows = [*Infield(board, anim, board_width, board_height).render(),
                # 三条固定行，顺序就是用户定的：投打 → 外野 → 传球
                *track_rows(board, anim, board_width)]
        for row in rows:
            text.append_text(row)
            text.append('\n')
        return {'board': text,
                'controls': render_controls(ui.controls if ui else None,
                                            board_width)}


register_renderer(BaseballRenderer())

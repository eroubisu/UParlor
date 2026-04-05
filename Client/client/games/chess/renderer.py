"""国际象棋渲染器 — 8×8 棋盘 + 棋子信息"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import register_renderer, render_doc

# 灰度色板（大厅 UI 部分）
_HEAD = 'bold #e0e0e0'
_DIM = '#808080'
_SCORE = '#b0b0b0'
_SEP = '#454545'

# 棋盘格色
_LIGHT_SQ = '#4a4a4a'
_DARK_SQ = '#333333'
_HIGHLIGHT = '#606060'
_CHECK_SQ = '#804040'

# 棋子色
_WHITE_PIECE = 'bold #E8E8E8'
_BLACK_PIECE = 'bold #707070'

# 文档高亮指令
_DOC_COMMANDS = {
    'create', 'rooms', 'start', 'bot', 'invite', 'kick',
    'resign', 'draw', 'accept', 'reject', 'back', 'help',
}

_FILE_LABELS = 'abcdefgh'
_RANK_LABELS = '12345678'


class ChessRenderer:
    """国际象棋渲染器"""

    game_type = 'chess'

    def render_board(self, room_data: dict) -> RenderableType:
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            return self._render_waiting(room_data)
        if state in ('playing', 'finished'):
            return self._render_game(room_data)
        return self._render_lobby(room_data)

    # ── 大厅 ──

    def _render_lobby(self, data: dict) -> RenderableType:
        parts = []
        doc = data.get('doc')
        if doc:
            parts.append(render_doc(doc, _DOC_COMMANDS))
        msg = data.get('message')
        if msg:
            t = Text()
            if parts:
                t.append('\n')
            for line in msg.split('\n'):
                t.append(f'  {line}\n', style=_SCORE)
            parts.append(t)
        if not parts:
            return Text('')
        if len(parts) == 1:
            return parts[0]
        combined = Text()
        for p in parts:
            combined.append_text(p) if isinstance(p, Text) else combined.append(str(p))
        return combined

    # ── 等待 ──

    def _render_waiting(self, data: dict) -> RenderableType:
        text = Text()
        room_id = data.get('room_id', '????')
        host = data.get('host', '???')
        players = data.get('players', [None, None])
        players_info = data.get('players_info', [])

        text.append('  ♔ 国际象棋\n\n', style=_HEAD)
        text.append(f'  房间 #{room_id}  房主: {host}\n', style=_SCORE)

        count = sum(1 for p in players if p)
        text.append(f'  等待中 ({count}/2)\n\n', style=_DIM)

        if players_info:
            for info in players_info:
                text.append(f'  {info}\n', style='#c0c0c0')
        else:
            labels = ['白方', '黑方']
            for i, p in enumerate(players):
                if p:
                    text.append(f'  [{labels[i]}] {p}\n', style='#c0c0c0')
                else:
                    text.append(f'  [{labels[i]}] ---\n', style=_SEP)

        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)
        return text

    # ── 游戏中 ──

    def _render_game(self, data: dict) -> RenderableType:
        text = Text()
        cells = data.get('cells', [None] * 64)
        last_move = data.get('last_move')
        in_check = data.get('in_check', False)
        turn = data.get('turn', 'white')
        players = data.get('players', [None, None])
        viewer_seat = data.get('viewer_seat')
        result = data.get('result')
        result_reason = data.get('result_reason', '')
        captured = data.get('captured', {'white': [], 'black': []})
        history = data.get('history', [])
        draw_offer = data.get('draw_offer', False)

        white_name = players[0] or '?'
        black_name = players[1] or '?'

        # 判断是否翻转棋盘 (黑方视角)
        flip = viewer_seat == 1

        last_squares = set(last_move) if last_move else set()

        # 找到被将军的国王格
        check_sq = None
        if in_check:
            king_type = 'king'
            king_color = turn
            for sq in range(64):
                c = cells[sq]
                if c and c['type'] == king_type and c['color'] == king_color:
                    check_sq = sq
                    break

        # 标题行
        turn_label = '白方' if turn == 'white' else '黑方'
        turn_name = white_name if turn == 'white' else black_name
        text.append('  ♔ 国际象棋', style=_HEAD)
        room_id = data.get('room_id', '')
        if room_id:
            text.append(f'  #{room_id}', style=_DIM)
        text.append('\n')

        # 对局信息
        text.append(f'  白 {white_name}  vs  黑 {black_name}\n', style=_SCORE)

        if result:
            text.append(f'  结果: {result} ({result_reason})\n', style=_HEAD)
        else:
            text.append(f'  {turn_label}({turn_name})走\n', style='bold #b8b8b8')

        text.append('\n')

        # 棋盘
        ranks = list(range(7, -1, -1)) if not flip else list(range(8))
        files = list(range(8)) if not flip else list(range(7, -1, -1))

        for rank in ranks:
            rank_label = _RANK_LABELS[rank]
            text.append(f'  {rank_label} ', style=_DIM)
            for file in files:
                sq = rank * 8 + file
                is_light = (rank + file) % 2 == 1

                # 背景色
                if sq == check_sq:
                    bg = _CHECK_SQ
                elif sq in last_squares:
                    bg = _HIGHLIGHT
                elif is_light:
                    bg = _LIGHT_SQ
                else:
                    bg = _DARK_SQ

                cell = cells[sq]
                if cell:
                    symbol = cell['symbol']
                    fg = '#E8E8E8' if cell['color'] == 'white' else '#707070'
                    text.append(f' {symbol} ', style=f'bold {fg} on {bg}')
                else:
                    text.append('   ', style=f'on {bg}')
            text.append('\n')

        # 文件标签
        text.append('    ', style=_DIM)
        for file in files:
            text.append(f' {_FILE_LABELS[file]} ', style=_DIM)
        text.append('\n')

        # 被吃棋子
        w_cap = captured.get('white', [])
        b_cap = captured.get('black', [])
        if w_cap or b_cap:
            text.append('\n')
            if b_cap:
                text.append('  白吃: ', style=_DIM)
                text.append(' '.join(b_cap), style=_BLACK_PIECE)
                text.append('\n')
            if w_cap:
                text.append('  黑吃: ', style=_DIM)
                text.append(' '.join(w_cap), style=_WHITE_PIECE)
                text.append('\n')

        # 走步历史
        if history:
            text.append('\n')
            for h in history[-5:]:
                text.append(f'  {h}\n', style=_DIM)

        # 和棋提议
        if draw_offer:
            text.append('\n  对方提议和棋。/accept 接受  /reject 拒绝\n',
                        style='bold #b8b8b8')

        # 消息
        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)

        return text


register_renderer(ChessRenderer())

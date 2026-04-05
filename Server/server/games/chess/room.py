"""国际象棋房间状态"""

from __future__ import annotations

import chess

# Unicode 棋子映射
_PIECE_SYMBOLS = {
    (chess.PAWN, chess.WHITE): '♙', (chess.PAWN, chess.BLACK): '♟',
    (chess.KNIGHT, chess.WHITE): '♘', (chess.KNIGHT, chess.BLACK): '♞',
    (chess.BISHOP, chess.WHITE): '♗', (chess.BISHOP, chess.BLACK): '♝',
    (chess.ROOK, chess.WHITE): '♖', (chess.ROOK, chess.BLACK): '♜',
    (chess.QUEEN, chess.WHITE): '♕', (chess.QUEEN, chess.BLACK): '♛',
    (chess.KING, chess.WHITE): '♔', (chess.KING, chess.BLACK): '♚',
}


class ChessRoom:
    """国际象棋房间

    players[0] = 白方, players[1] = 黑方
    """

    def __init__(self, room_id: str, host: str):
        self.room_id = room_id
        self.host = host
        self.state = 'waiting'  # waiting → playing → finished
        self.players: list[str | None] = [host, None]
        self.bots: set[str] = set()
        self.board: chess.Board = chess.Board()
        self.move_history: list[str] = []
        self.result: str | None = None  # '1-0', '0-1', '1/2-1/2'
        self.result_reason: str = ''
        self._draw_offer_from: int | None = None  # seat index

    @property
    def player_count(self) -> int:
        return sum(1 for p in self.players if p)

    def is_full(self) -> bool:
        return self.player_count >= 2

    def is_bot(self, name: str) -> bool:
        return name in self.bots

    def add_player(self, name: str) -> bool:
        for i in range(2):
            if self.players[i] is None:
                self.players[i] = name
                return True
        return False

    def remove_player(self, name: str):
        for i in range(2):
            if self.players[i] == name:
                self.players[i] = None
        self.bots.discard(name)

    def get_seat(self, name: str) -> int | None:
        for i in range(2):
            if self.players[i] == name:
                return i
        return None

    def current_player(self) -> str | None:
        """当前轮到谁走"""
        idx = 0 if self.board.turn == chess.WHITE else 1
        return self.players[idx]

    def try_move(self, uci_str: str) -> chess.Move | None:
        """尝试走棋（UCI格式），合法返回 Move，否则 None"""
        try:
            move = chess.Move.from_uci(uci_str)
        except (ValueError, chess.InvalidMoveError):
            return None
        if move not in self.board.legal_moves:
            # 尝试带升变 (自动皇后)
            promo = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
            if promo in self.board.legal_moves:
                move = promo
            else:
                return None
        self.board.push(move)
        self.move_history.append(move.uci())
        self._draw_offer_from = None
        self._check_game_over()
        return move

    def _check_game_over(self):
        b = self.board
        if b.is_checkmate():
            self.state = 'finished'
            self.result = '1-0' if b.turn == chess.BLACK else '0-1'
            self.result_reason = '将杀'
        elif b.is_stalemate():
            self.state = 'finished'
            self.result = '1/2-1/2'
            self.result_reason = '逼和'
        elif b.is_insufficient_material():
            self.state = 'finished'
            self.result = '1/2-1/2'
            self.result_reason = '子力不足'
        elif b.is_fifty_moves():
            self.state = 'finished'
            self.result = '1/2-1/2'
            self.result_reason = '50步规则'
        elif b.is_repetition(3):
            self.state = 'finished'
            self.result = '1/2-1/2'
            self.result_reason = '三次重复'

    def resign(self, seat: int):
        self.state = 'finished'
        self.result = '0-1' if seat == 0 else '1-0'
        self.result_reason = '认输'

    def accept_draw(self):
        self.state = 'finished'
        self.result = '1/2-1/2'
        self.result_reason = '协议和棋'

    def start(self):
        self.board = chess.Board()
        self.move_history.clear()
        self.state = 'playing'
        self.result = None
        self.result_reason = ''
        self._draw_offer_from = None

    def get_game_data(self, viewer: str | None = None) -> dict:
        """构建客户端渲染用数据"""
        b = self.board
        # 棋盘 8×8 数据: list of 64 cells (a1=0, h8=63)
        cells: list[dict | None] = []
        for sq in range(64):
            piece = b.piece_at(sq)
            if piece:
                cells.append({
                    'symbol': _PIECE_SYMBOLS.get((piece.piece_type, piece.color), '?'),
                    'type': chess.piece_name(piece.piece_type),
                    'color': 'white' if piece.color == chess.WHITE else 'black',
                })
            else:
                cells.append(None)

        # 最后一步的起止格
        last_move = None
        if self.move_history:
            m = chess.Move.from_uci(self.move_history[-1])
            last_move = [m.from_square, m.to_square]

        viewer_seat = self.get_seat(viewer) if viewer else None
        current_seat = 0 if b.turn == chess.WHITE else 1

        data = {
            'game_type': 'chess',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'players': self.players,
            'cells': cells,
            'turn': 'white' if b.turn == chess.WHITE else 'black',
            'current_seat': current_seat,
            'viewer_seat': viewer_seat,
            'in_check': b.is_check(),
            'last_move': last_move,
            'move_count': len(self.move_history),
            'fen': b.fen(),
        }

        if self.state == 'finished':
            data['result'] = self.result
            data['result_reason'] = self.result_reason
            winner_seat = None
            if self.result == '1-0':
                winner_seat = 0
            elif self.result == '0-1':
                winner_seat = 1
            data['winner'] = self.players[winner_seat] if winner_seat is not None else None
            data['winner_seat'] = winner_seat

        if self._draw_offer_from is not None and viewer_seat is not None:
            if self._draw_offer_from != viewer_seat:
                data['draw_offer'] = True

        # 被吃的棋子
        captured = {'white': [], 'black': []}
        tmp = chess.Board()
        for uci in self.move_history:
            m = chess.Move.from_uci(uci)
            cap = tmp.piece_at(m.to_square)
            if cap:
                color = 'white' if cap.color == chess.WHITE else 'black'
                sym = _PIECE_SYMBOLS.get((cap.piece_type, cap.color), '?')
                captured[color].append(sym)
            tmp.push(m)
        data['captured'] = captured

        # 最近走步文本
        history_text = []
        for i in range(0, len(self.move_history), 2):
            n = i // 2 + 1
            w = self.move_history[i]
            b_move = self.move_history[i + 1] if i + 1 < len(self.move_history) else ''
            history_text.append(f'{n}. {w} {b_move}'.strip())
        data['history'] = history_text[-10:]  # 最近 10 步

        return data

    def get_table_data(self) -> dict:
        color_label = ['白', '黑']
        players_info = []
        for i, p in enumerate(self.players):
            if p:
                players_info.append(f'{p}({color_label[i]})')
        return {
            'game_type': 'chess',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'players': self.players,
            'players_info': players_info,
            'player_count': self.player_count,
        }

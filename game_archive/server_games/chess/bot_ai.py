"""
国际象棋 AI — 纯 python-chess 实现
minimax + alpha-beta 剪枝 + 静态搜索 (quiescence)
不依赖外部引擎（Stockfish）
"""

import random
import chess

# 子力价值（centipawns）
PIECE_VALUES = {
    chess.PAWN:   100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK:   500,
    chess.QUEEN:  900,
    chess.KING:   0,
}

# 位置加分表（从白方视角，a1=index 0, h8=index 63）
PAWN_TABLE = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]

KNIGHT_TABLE = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
]

BISHOP_TABLE = [
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  5,  0,  5,  5,  0,  5,-10,
    -10,  0,  5,  0,  0,  5,  0,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
]

ROOK_TABLE = [
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10, 10, 10, 10, 10,  5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     0,  0,  0,  5,  5,  0,  0,  0,
]

QUEEN_TABLE = [
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
]

KING_MID_TABLE = [
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
]

KING_END_TABLE = [
    -50,-40,-30,-20,-20,-30,-40,-50,
    -30,-20,-10,  0,  0,-10,-20,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-30,  0,  0,  0,  0,-30,-30,
    -50,-30,-30,-30,-30,-30,-30,-50,
]

PST = {
    chess.PAWN:   PAWN_TABLE,
    chess.KNIGHT: KNIGHT_TABLE,
    chess.BISHOP: BISHOP_TABLE,
    chess.ROOK:   ROOK_TABLE,
    chess.QUEEN:  QUEEN_TABLE,
}


def _is_endgame(board):
    """粗略判断是否进入残局"""
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK))
    minors = (len(board.pieces(chess.KNIGHT, chess.WHITE)) + len(board.pieces(chess.BISHOP, chess.WHITE)) +
              len(board.pieces(chess.KNIGHT, chess.BLACK)) + len(board.pieces(chess.BISHOP, chess.BLACK)))
    return queens == 0 or (queens <= 2 and minors <= 2)


def evaluate_board(board):
    """静态局面评估（从白方视角，正值为白方优势）"""
    if board.is_checkmate():
        return -99999 if board.turn == chess.WHITE else 99999
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    endgame = _is_endgame(board)
    score = 0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None:
            continue
        value = PIECE_VALUES.get(piece.piece_type, 0)
        # 位置加分
        if piece.piece_type == chess.KING:
            pst = KING_END_TABLE if endgame else KING_MID_TABLE
        else:
            pst = PST.get(piece.piece_type)
        if pst:
            idx = sq if piece.color == chess.WHITE else chess.square_mirror(sq)
            value += pst[idx]
        score += value if piece.color == chess.WHITE else -value

    # 机动性奖励（合法走法数）
    mobility = board.legal_moves.count()
    score += (mobility if board.turn == chess.WHITE else -mobility) * 3

    return score


def _move_sort_key(board, move):
    """着法排序分值（越大越优先搜索）"""
    score = 0
    # 吃子: MVV-LVA
    if board.is_capture(move):
        victim = board.piece_type_at(move.to_square)
        attacker = board.piece_type_at(move.from_square)
        if victim and attacker:
            score += PIECE_VALUES.get(victim, 0) * 10 - PIECE_VALUES.get(attacker, 0)
        else:
            score += 500
    # 升变
    if move.promotion:
        score += PIECE_VALUES.get(move.promotion, 0)
    # 将军
    if board.gives_check(move):
        score += 800
    return score


def _order_moves(board):
    """着法排序：将军 > 吃子(MVV-LVA) > 升变 > 其余随机"""
    moves = list(board.legal_moves)
    moves.sort(key=lambda m: _move_sort_key(board, m), reverse=True)
    # 对同分着法做少量随机化避免千篇一律
    i = 0
    while i < len(moves):
        j = i + 1
        k = _move_sort_key(board, moves[i])
        while j < len(moves) and _move_sort_key(board, moves[j]) == k:
            j += 1
        if j - i > 1:
            sub = moves[i:j]
            random.shuffle(sub)
            moves[i:j] = sub
        i = j
    return moves


def quiescence(board, alpha, beta, maximizing):
    """静态搜索 — 只搜索吃子走法，消除水平线效应"""
    stand_pat = evaluate_board(board)

    if maximizing:
        if stand_pat >= beta:
            return beta
        alpha = max(alpha, stand_pat)
        for move in board.legal_moves:
            if not board.is_capture(move):
                continue
            board.push(move)
            val = quiescence(board, alpha, beta, False)
            board.pop()
            if val >= beta:
                return beta
            alpha = max(alpha, val)
        return alpha
    else:
        if stand_pat <= alpha:
            return alpha
        beta = min(beta, stand_pat)
        for move in board.legal_moves:
            if not board.is_capture(move):
                continue
            board.push(move)
            val = quiescence(board, alpha, beta, True)
            board.pop()
            if val <= alpha:
                return alpha
            beta = min(beta, val)
        return beta


def minimax(board, depth, alpha, beta, maximizing):
    """带 alpha-beta 剪枝的 minimax + quiescence"""
    if board.is_game_over():
        return evaluate_board(board), None
    if depth == 0:
        return quiescence(board, alpha, beta, maximizing), None

    best_move = None
    if maximizing:
        max_eval = -999999
        for move in _order_moves(board):
            board.push(move)
            val, _ = minimax(board, depth - 1, alpha, beta, False)
            board.pop()
            if val > max_eval:
                max_eval = val
                best_move = move
            alpha = max(alpha, val)
            if beta <= alpha:
                break
        return max_eval, best_move
    else:
        min_eval = 999999
        for move in _order_moves(board):
            board.push(move)
            val, _ = minimax(board, depth - 1, alpha, beta, True)
            board.pop()
            if val < min_eval:
                min_eval = val
                best_move = move
            beta = min(beta, val)
            if beta <= alpha:
                break
        return min_eval, best_move


def get_best_move(board, depth=3):
    """获取 AI 最佳走法"""
    maximizing = board.turn == chess.WHITE
    _, move = minimax(board, depth, -999999, 999999, maximizing)
    if move is None:
        # fallback: 随机合法走法
        legal = list(board.legal_moves)
        if legal:
            move = random.choice(legal)
    return move

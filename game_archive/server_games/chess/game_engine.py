"""
国际象棋 - 对局结果格式化工具
（对局逻辑已由 room.py 负责，此模块仅保留辅助函数）
"""


def format_game_result(result):
    """格式化对局结果为文字"""
    if result is None:
        return None

    rtype = result.get('type')
    if rtype == 'checkmate':
        return f"♔ 将杀！{result['winner_name']} 获胜！"
    elif rtype == 'resign':
        return f"🏳 {result['loser_name']} 认输，{result['winner_name']} 获胜！"
    elif rtype == 'timeout':
        return f"⏰ {result['loser_name']} 超时，{result['winner_name']} 获胜！"
    elif rtype == 'draw':
        reason_map = {
            'agreement': '双方同意和棋',
            'stalemate': '逼和（无合法走法）',
            'insufficient_material': '子力不足',
            'fifty_moves': '50步规则',
            'repetition': '三次重复局面',
        }
        reason = reason_map.get(result.get('reason'), '和棋')
        return f"🤝 {reason}，对局和棋"
    elif rtype == 'check':
        return "♚ 将军！"
    return None

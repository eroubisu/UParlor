"""
国际象棋数据管理（保留扩展接口）
"""


class ChessData:
    """国际象棋数据管理"""

    # AI 难度配置: depth 为搜索深度
    DIFFICULTIES = {
        'easy':   {'name': '简单', 'depth': 1},
        'normal': {'name': '普通', 'depth': 2},
        'hard':   {'name': '困难', 'depth': 3},
    }

    DEFAULT_DIFFICULTY = 'normal'

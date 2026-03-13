"""
JRPG 游戏模块
"""

from .game_data import JRPGData
from .game_engine import JRPGEngine

# 游戏信息
GAME_INFO = {
    'id': 'jrpg',
    'name': 'JRPG冒险',
    'description': '一个简单的文字冒险RPG游戏',
    'min_players': 1,
    'max_players': 1,
    'icon': '⚔',
    'has_rooms': False,
    'has_bot': False,
    'per_player': True,
    'rank_key': None,
    'locations': {
        'jrpg': ('JRPG', 'lobby'),
    },
    'create_engine': lambda: JRPGEngine(JRPGData()),
}

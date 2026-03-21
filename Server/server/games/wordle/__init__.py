"""Wordle — 猜词游戏模块注册

per_player=False: 共享引擎实例，房间制管理
locations parent 指向 world_gamehall（棋馆建筑）
"""

from .engine import WordleEngine

GAME_INFO = {
    'id': 'wordle',
    'name': 'wordle',
    'icon': 'W',
    'per_player': False,
    'create_engine': WordleEngine,
    'locations': {
        'wordle_lobby':    ('wordle', 'world_library'),
        'wordle_room':     ('房间', 'wordle_lobby'),
        'wordle_playing':  ('游戏中', 'wordle_room'),
        'wordle_finished': ('结算', 'wordle_room'),
    },
}

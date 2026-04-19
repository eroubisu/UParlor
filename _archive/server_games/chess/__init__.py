"""国际象棋 — 游戏模块注册

per_player=False: 共享引擎实例，房间制管理
"""

from __future__ import annotations

from .engine import ChessEngine, create_bot_scheduler

GAME_INFO = {
    'id': 'chess',
    'name': '国际象棋',
    'icon': '♔',
    'per_player': False,
    'create_engine': ChessEngine,
    'create_bot_scheduler': create_bot_scheduler,
    'locations': {
        'chess_lobby':   ('国际象棋', 'lobby'),
        'chess_room':    ('房间', 'chess_lobby'),
        'chess_playing': ('游戏中', 'chess_room'),
    },
}

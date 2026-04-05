"""日本麻将 — 游戏模块注册

per_player=False: 共享引擎实例，房间制管理
locations parent 指向 building_gamehall（棋牌室建筑）
"""

from __future__ import annotations

from .engine import MahjongEngine, create_bot_scheduler

GAME_INFO = {
    'id': 'mahjong',
    'name': '麻将',
    'icon': 'M',
    'per_player': False,
    'create_engine': MahjongEngine,
    'create_bot_scheduler': create_bot_scheduler,
    'locations': {
        'mahjong_lobby':   ('麻将', 'building_gamehall'),
        'mahjong_room':    ('房间', 'mahjong_lobby'),
        'mahjong_playing': ('游戏中', 'mahjong_room'),
    },
}

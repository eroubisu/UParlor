"""斗地主 — 游戏模块注册"""

from __future__ import annotations

from .engine import DoudizhuEngine, create_bot_scheduler

GAME_INFO = {
    'id': 'doudizhu',
    'name': '斗地主',
    'icon': '*',
    'per_player': False,
    'create_engine': DoudizhuEngine,
    'create_bot_scheduler': create_bot_scheduler,
    'locations': {
        'doudizhu_lobby':   ('斗地主', 'lobby'),
        'doudizhu_room':    ('房间', 'doudizhu_lobby'),
        'doudizhu_playing': ('游戏中', 'doudizhu_room'),
    },
}

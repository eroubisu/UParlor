"""21点 — 游戏模块注册"""

from __future__ import annotations

from .engine import BlackjackEngine, create_bot_scheduler

GAME_INFO = {
    'id': 'blackjack',
    'name': '21点',
    'icon': 'A',
    'per_player': False,
    'create_engine': BlackjackEngine,
    'create_bot_scheduler': create_bot_scheduler,
    'locations': {
        'blackjack_lobby':   ('21点', 'lobby'),
        'blackjack_room':    ('房间', 'blackjack_lobby'),
        'blackjack_playing': ('游戏中', 'blackjack_room'),
    },
}

"""德州扑克 — 游戏模块注册"""

from __future__ import annotations

from .engine import HoldemEngine, create_bot_scheduler

GAME_INFO = {
    'id': 'holdem',
    'name': '德州扑克',
    'icon': '♠',
    'per_player': False,
    'create_engine': HoldemEngine,
    'create_bot_scheduler': create_bot_scheduler,
    'locations': {
        'holdem_lobby':   ('德州扑克', 'building_casino'),
        'holdem_room':    ('房间', 'holdem_lobby'),
        'holdem_playing': ('游戏中', 'holdem_room'),
    },
}

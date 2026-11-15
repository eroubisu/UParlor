"""棒球 — 游戏模块注册（1v1，局数创建房间时选）"""

from __future__ import annotations

from .engine import BaseballEngine, create_bot_scheduler
from .room import DEFAULT_INNINGS

GAME_INFO = {
    'id': 'baseball',
    'name': '棒球',
    'icon': '\uf140',
    'description': '1v1 棒球：投打读心、外野逐格追球、手动接球与跑垒',
    'min_players': 2,
    'max_players': 2,
    'start_policy': {
        'minimum_players': 2,
        'underfilled': BaseballEngine.underfilled_start,
    },
    'per_player': False,
    'create_engine': BaseballEngine,
    'create_bot_scheduler': create_bot_scheduler,
    'locations': {},
    'room_settings': [
        {
            'key': 'innings',
            'label': '局数',
            'options': [{'value': n, 'label': f'{n} 局'}
                        for n in range(1, 10)],
            'default': DEFAULT_INNINGS,
        },
    ],
}

"""飞行棋 — 游戏模块注册"""

from __future__ import annotations

from .engine import LudoEngine, create_bot_scheduler

GAME_INFO = {
    'id': 'ludo',
    'name': '飞行棋',
    'icon': '\uf072',
    'description': '2-4人经典飞行棋，掷骰起飞，先完成所有棋子者获胜',
    'min_players': 2,
    'max_players': 4,
    'start_policy': {
        'minimum_players': 2,
        'underfilled': LudoEngine.underfilled_start,
    },
    'per_player': False,
    'create_engine': LudoEngine,
    'create_bot_scheduler': create_bot_scheduler,
    'locations': {},
    'room_settings': [
        {
            'key': 'mode',
            'label': '模式',
            'options': [
                {'value': 'casual', 'label': '休闲'},
                {'value': 'ranked', 'label': '竞技'},
            ],
            'default': 'casual',
        },
        {
            'key': 'max_players',
            'label': '最大人数',
            'options': [{'value': n, 'label': str(n)} for n in range(2, 5)],
            'default': 4,
        },
    ],
}

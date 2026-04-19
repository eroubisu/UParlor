"""UNO Flip — 游戏模块注册"""

from __future__ import annotations

from .engine import UnoEngine, create_bot_scheduler

GAME_INFO = {
    'id': 'uno',
    'name': 'UNO Flip',
    'icon': '\uf24d',
    'description': '双面牌翻转游戏，匹配颜色或数字出牌，先出完者获胜',
    'min_players': 2,
    'max_players': 10,
    'per_player': False,
    'create_engine': UnoEngine,
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
            'options': [{'value': n, 'label': str(n)} for n in range(2, 11)],
            'default': 6,
        },
        {
            'key': 'draw_stacking',
            'label': 'Draw叠加',
            'options': [
                {'value': True, 'label': '开'},
                {'value': False, 'label': '关'},
            ],
            'default': True,
        },
        {
            'key': 'challenge',
            'label': '挑战规则',
            'options': [
                {'value': True, 'label': '开'},
                {'value': False, 'label': '关'},
            ],
            'default': True,
        },
    ],
}

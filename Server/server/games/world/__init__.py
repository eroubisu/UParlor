"""开放世界 — 游戏模块注册

per_player=True: 每个玩家独立引擎实例
玩家登录后直接身处世界
"""

from __future__ import annotations

import json
import os

from .engine import WorldEngine

_dir = os.path.dirname(__file__)


def _load_json(name):
    path = os.path.join(_dir, 'data', name)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


GAME_INFO = {
    'id': 'world',
    'name': '开放世界',
    'icon': 'W',
    'per_player': True,
    'create_engine': WorldEngine,
    'locations': {
        'world_town':          ('城镇', None),
        'building_blacksmith': ('铁匠铺', 'world_town'),
        'building_herbshop':   ('药草店', 'world_town'),
        'building_guild':      ('冒险者公会', 'world_town'),
        'building_gamehall':   ('棋牌室', 'world_town'),
        'building_tavern':     ('酒馆', 'world_town'),
        'building_library':    ('文字馆', 'world_town'),
        'building_casino':     ('赌场', 'world_town'),
        'building_chesshall':  ('棋馆', 'world_town'),
        'building_fishery':    ('渔具店', 'world_town'),
        'building_empty':      ('空房', 'world_town'),
    },
    'recipes': _load_json('recipes.json'),
}

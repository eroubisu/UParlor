"""用户属性模板与数据完整性

所有静态数据从 JSON 文件加载：
  - ranks.json   — 默认段位阶梯（通用/后备）
  - titles.json  — 系统/社交/活动头衔
  - items.json   — 系统物品

段位/头衔/物品的查询与注册分别在：
  - rank_system.py
  - title_system.py
  - item_system.py
"""

from datetime import datetime
import copy
import json
import os


# ══════════════════════════════════════════════════
#  从 JSON 加载框架级静态数据
# ══════════════════════════════════════════════════

_dir = os.path.join(os.path.dirname(__file__), '..', 'data')


def _load_json(filename):
    path = os.path.join(_dir, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


_ranks_data = _load_json('ranks.json')
RANKS = _ranks_data['ranks']
RANK_ORDER = _ranks_data['rank_order']
_DEFAULT_RANK_TO_TITLE = _ranks_data.get('rank_to_title', {})

_titles_data = _load_json('titles.json')
TITLE_LIBRARY = _titles_data['titles']
TITLE_SOURCES = _titles_data['sources']

_items_data = _load_json('items.json')
ITEM_LIBRARY = _items_data['items']
ITEM_SOURCES = _items_data['sources']


# ══════════════════════════════════════════════════
#  游戏玩家默认数据注册
# ══════════════════════════════════════════════════

_GAME_PLAYER_DEFAULTS = {}   # {game_id: {默认玩家数据}}


def register_game_player_defaults(game_id: str, defaults: dict) -> None:
    _GAME_PLAYER_DEFAULTS[game_id] = defaults


# ══════════════════════════════════════════════════
#  默认用户属性模板
# ══════════════════════════════════════════════════

def get_default_user_template(name="", password_hash=""):
    template = {
        'name': name,
        'password_hash': password_hash,
        'created_at': datetime.now().isoformat(),

        'level': 1,
        'exp': 0,
        'gold': 100,
        'accessory': None,

        'social_stats': {
            'login_days': 0,
            'last_login_date': '',
            'chat_messages': 0,
            'invites_sent': 0,
        },

        'friends': [],

        'game_stats': {
            'total_games': 0,
            'total_wins': 0,
            'total_losses': 0,
            'total_draws': 0,
        },

        'inventory': {
            'rename_card': 2,
        },

        'titles': {
            'owned': ['newcomer'],
            'displayed': ['newcomer'],
        },

        'window_layout': None,

        'ai_companions': {},
        'ai_token_stats': {},
    }

    for game_id, defaults in _GAME_PLAYER_DEFAULTS.items():
        template[game_id] = copy.deepcopy(defaults)

    return template


# ══════════════════════════════════════════════════
#  数据完整性
# ══════════════════════════════════════════════════

def ensure_user_schema(user_data):
    """确保用户数据包含所有必需属性。Returns: (data, changes)"""
    if not user_data:
        return None, []

    template = get_default_user_template()
    changes = []

    # ── 历史数据迁移 ──

    if 'rename_cards' in user_data and 'inventory' not in user_data:
        user_data['inventory'] = {'rename_card': user_data.pop('rename_cards', 2)}
        changes.append("迁移: rename_cards -> inventory.rename_card")
    elif 'rename_cards' in user_data:
        user_data.pop('rename_cards', None)
        changes.append("删除: 旧字段 rename_cards")

    if 'title' in user_data:
        user_data.pop('title', None)
        changes.append("删除: 旧字段 title")

    _name_to_id = {info['name']: tid for tid, info in TITLE_LIBRARY.items()}
    titles = user_data.get('titles')
    if titles:
        for key in ('owned', 'displayed'):
            lst = titles.get(key, [])
            migrated = []
            for t in lst:
                if t in _name_to_id:
                    migrated.append(_name_to_id[t])
                    changes.append(f"迁移头衔: '{t}' -> '{_name_to_id[t]}'")
                else:
                    migrated.append(t)
            titles[key] = migrated

    games_data = user_data.get('games', {})
    if isinstance(games_data, dict) and games_data:
        for game_id in list(games_data.keys()):
            game_sub = games_data.pop(game_id)
            if isinstance(game_sub, dict):
                if 'gold' in game_sub:
                    user_data['gold'] = user_data.get('gold', 0) + game_sub.pop('gold', 0)
                    changes.append(f"迁移: games.{game_id}.gold -> gold")
                if game_id not in user_data and game_sub:
                    user_data[game_id] = game_sub
                    changes.append(f"迁移: games.{game_id} -> {game_id}")
        if not games_data:
            user_data.pop('games', None)
            changes.append("删除: 空的 games 字段")

    # ── 递归补全缺失字段 ──

    def merge_dict(target, source, path=""):
        for key, default_value in source.items():
            current_path = f"{path}.{key}" if path else key
            if key in ('name', 'password_hash', 'created_at'):
                continue
            if key not in target:
                target[key] = copy.deepcopy(default_value)
                changes.append(f"添加: {current_path}")
            elif isinstance(default_value, dict) and isinstance(target[key], dict):
                merge_dict(target[key], default_value, current_path)

    merge_dict(user_data, template)
    return user_data, changes

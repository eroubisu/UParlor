"""用户属性模板与数据完整性

所有静态数据从 JSON 文件加载：
  - ranks.json   — 默认段位阶梯（通用/后备）
  - titles.json  — 系统/社交/活动头衔

段位/头衔的查询与注册分别在 systems/ranks.py、systems/titles.py。
"""

from __future__ import annotations

from datetime import datetime
import copy

from ..systems.titles import TITLE_LIBRARY


# ── 名片默认值 ──

DEFAULT_CARD_FIELDS = ['level', 'gold', 'games', 'created']
DEFAULT_NAME_COLOR = '#ffffff'
DEFAULT_MOTTO_COLOR = '#b3b3b3'
DEFAULT_BORDER_COLOR = '#5a5a5a'


# ── 游戏玩家默认数据注册 ──

_GAME_PLAYER_DEFAULTS = {}   # {game_id: {默认玩家数据}}


def default_titles() -> dict:
    """返回默认头衔字典（深拷贝）— 所有需要 titles 默认值的地方统一调用此函数"""
    from ..config import DEFAULT_TITLE_ID
    return {'owned': [DEFAULT_TITLE_ID], 'displayed': [DEFAULT_TITLE_ID]}


def register_game_player_defaults(game_id: str, defaults: dict) -> None:
    _GAME_PLAYER_DEFAULTS[game_id] = defaults


# ── 默认用户属性模板 ──

def get_default_user_template(name="", password_hash=""):
    template = {
        'name': name,
        'password_hash': password_hash,
        'created_at': datetime.now().isoformat(),

        'level': 1,
        'exp': 0,
        'gold': 100,
        'accessory': None,

        'profile_card': {
            'motto': '',
            'name_color': DEFAULT_NAME_COLOR,
            'motto_color': DEFAULT_MOTTO_COLOR,
            'border_color': DEFAULT_BORDER_COLOR,
            'card_fields': list(DEFAULT_CARD_FIELDS),
        },

        'friends': [],

        'game_stats': {
            'total_games': 0,
            'total_wins': 0,
            'total_losses': 0,
            'total_draws': 0,
        },

        'inventory': {},

        'titles': default_titles(),

        'window_layout': None,
    }

    for game_id, defaults in _GAME_PLAYER_DEFAULTS.items():
        template[game_id] = copy.deepcopy(defaults)

    return template


# ── 数据完整性 ──

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

    # ── 删除废弃字段 ──
    for field in ('attributes', 'equipment'):
        if field in user_data:
            user_data.pop(field)
            changes.append(f"删除: 废弃字段 {field}")

    # ── 迁移品质格式库存 {item_id: {"0": count}} → {item_id: count} ──
    inv = user_data.get('inventory')
    if isinstance(inv, dict):
        for iid in list(inv.keys()):
            val = inv[iid]
            if isinstance(val, dict):
                total = sum(v for v in val.values() if isinstance(v, int))
                inv[iid] = total
                changes.append(f"迁移库存: {iid} 品质格式 -> 简单计数")
            # 删除已移除的物品
            if iid in ('healing_herb', 'teleport_stone', 'enchanted_ring',
                        'iron_ore', 'dragon_scale', 'raw_fish', 'rare_fish',
                        'iron_sword', 'steel_sword', 'leather_armor', 'iron_armor',
                        'iron_helmet', 'leather_boots', 'iron_boots', 'wooden_shield',
                        'iron_shield', 'leather_gloves', 'traveler_cloak',
                        'silver_necklace', 'jade_earring', 'strength_ring',
                        'leather_belt', 'lucky_charm', 'fishing_rod'):
                inv.pop(iid, None)
                changes.append(f"删除: 已移除物品 {iid}")

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

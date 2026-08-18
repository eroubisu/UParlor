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
from .chat_style import default_chat_style, validate_chat_style


# ── 名片默认值 ──

DEFAULT_CARD_FIELDS = ['level', 'gold', 'games', 'created']
DEFAULT_NAME_COLOR = '#ffffff'
DEFAULT_MOTTO_COLOR = '#b3b3b3'
DEFAULT_BORDER_COLOR = '#5a5a5a'
_REMOVED_INVENTORY_ITEMS = frozenset({
    'healing_herb', 'teleport_stone', 'enchanted_ring',
    'iron_ore', 'dragon_scale', 'raw_fish', 'rare_fish',
    'iron_sword', 'steel_sword', 'leather_armor', 'iron_armor',
    'iron_helmet', 'leather_boots', 'iron_boots', 'wooden_shield',
    'iron_shield', 'leather_gloves', 'traveler_cloak',
    'silver_necklace', 'jade_earring', 'strength_ring',
    'leather_belt', 'lucky_charm', 'fishing_rod',
})


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
        'chat_style': default_chat_style(),

        'friends': [],
        'pending_friend_requests': [],

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

def _migrate_legacy_fields(user_data: dict, changes: list[str]) -> None:
    if 'rename_cards' in user_data and 'inventory' not in user_data:
        user_data['inventory'] = {'rename_card': user_data.pop('rename_cards', 2)}
        changes.append("迁移: rename_cards -> inventory.rename_card")
    elif 'rename_cards' in user_data:
        user_data.pop('rename_cards', None)
        changes.append("删除: 旧字段 rename_cards")

    if 'title' in user_data:
        user_data.pop('title', None)
        changes.append("删除: 旧字段 title")


def _migrate_titles(user_data: dict, changes: list[str]) -> None:
    name_to_id = {info['name']: tid for tid, info in TITLE_LIBRARY.items()}
    titles = user_data.get('titles')
    if not titles:
        return
    for key in ('owned', 'displayed'):
        migrated = []
        for title in titles.get(key, []):
            if title in name_to_id:
                migrated.append(name_to_id[title])
                changes.append(
                    f"迁移头衔: '{title}' -> '{name_to_id[title]}'")
            else:
                migrated.append(title)
        titles[key] = migrated


def _migrate_games(user_data: dict, changes: list[str]) -> None:
    games_data = user_data.get('games', {})
    if not isinstance(games_data, dict) or not games_data:
        return
    for game_id in list(games_data.keys()):
        game_data = games_data.pop(game_id)
        if not isinstance(game_data, dict):
            continue
        if 'gold' in game_data:
            user_data['gold'] = (
                user_data.get('gold', 0) + game_data.pop('gold', 0)
            )
            changes.append(f"迁移: games.{game_id}.gold -> gold")
        if game_id not in user_data and game_data:
            user_data[game_id] = game_data
            changes.append(f"迁移: games.{game_id} -> {game_id}")
    if not games_data:
        user_data.pop('games', None)
        changes.append("删除: 空的 games 字段")


def _remove_deprecated_fields(user_data: dict, changes: list[str]) -> None:
    for field in ('attributes', 'equipment'):
        if field in user_data:
            user_data.pop(field)
            changes.append(f"删除: 废弃字段 {field}")


def _migrate_inventory(user_data: dict, changes: list[str]) -> None:
    inv = user_data.get('inventory')
    if not isinstance(inv, dict):
        return
    for item_id in list(inv.keys()):
        value = inv[item_id]
        if isinstance(value, dict):
            inv[item_id] = sum(
                count for count in value.values()
                if isinstance(count, int)
            )
            changes.append(
                f"迁移库存: {item_id} 品质格式 -> 简单计数")
        if item_id in _REMOVED_INVENTORY_ITEMS:
            inv.pop(item_id, None)
            changes.append(f"删除: 已移除物品 {item_id}")


def _merge_defaults(
    target: dict,
    source: dict,
    changes: list[str],
    path: str = "",
) -> None:
    for key, default_value in source.items():
        current_path = f"{path}.{key}" if path else key
        if key in ('name', 'password_hash', 'created_at'):
            continue
        if key not in target:
            target[key] = copy.deepcopy(default_value)
            changes.append(f"添加: {current_path}")
        elif isinstance(default_value, dict) and isinstance(target[key], dict):
            _merge_defaults(target[key], default_value, changes, current_path)


def ensure_user_schema(user_data):
    """确保用户数据包含所有必需属性。Returns: (data, changes)"""
    if not user_data:
        return None, []

    changes = []
    _migrate_legacy_fields(user_data, changes)
    _migrate_titles(user_data, changes)
    _migrate_games(user_data, changes)
    _remove_deprecated_fields(user_data, changes)
    _migrate_inventory(user_data, changes)
    _merge_defaults(user_data, get_default_user_template(), changes)

    titles = user_data.get('titles', {})
    validated_style = validate_chat_style(
        user_data.get('chat_style'),
        titles.get('owned', []) if isinstance(titles, dict) else [],
    )
    if user_data.get('chat_style') != validated_style:
        user_data['chat_style'] = validated_style
        changes.append("规范化: chat_style")
    return user_data, changes

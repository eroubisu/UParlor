"""属性系统 — 玩家基础属性 + 装备加成计算

数据来源: data/attributes.json
玩家数据: player_data['attributes'] 存储当前 HP/MP
属性总值: 基础(等级) + 装备加成
"""

from __future__ import annotations

import json
import os

_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
with open(os.path.join(_dir, 'attributes.json'), 'r', encoding='utf-8') as _f:
    _ATTR_CFG = json.load(_f)

BASE_ATTRIBUTES: dict = _ATTR_CFG['base_attributes']
EQUIPMENT_SLOTS: dict[str, str] = _ATTR_CFG['equipment_slots']


def get_base_stats(level: int) -> dict[str, int]:
    """计算指定等级的基础属性（不含装备）"""
    stats = {}
    for attr_id, info in BASE_ATTRIBUTES.items():
        base = info.get('base', 0)
        per_level = info.get('per_level', 0)
        stats[attr_id] = base + per_level * (level - 1)
    return stats


def get_equipment_bonus(player_data: dict) -> dict[str, int]:
    """计算装备总加成"""
    bonus: dict[str, int] = {}
    equipment = player_data.get('equipment', {})
    from .items import get_item_info
    for slot, item_entry in equipment.items():
        if not isinstance(item_entry, dict):
            continue
        item_id = item_entry.get('id')
        if not item_id:
            continue
        info = get_item_info(item_id)
        if info and info.get('stats'):
            for stat, value in info['stats'].items():
                bonus[stat] = bonus.get(stat, 0) + value
    return bonus


def get_total_stats(player_data: dict) -> dict[str, int]:
    """计算总属性 = 基础(等级) + 装备加成"""
    level = player_data.get('level', 1)
    stats = get_base_stats(level)
    for stat, value in get_equipment_bonus(player_data).items():
        if stat in stats:
            stats[stat] += value
    return stats


def get_max_hp(player_data: dict) -> int:
    return get_total_stats(player_data).get('hp', 100)


def get_max_mp(player_data: dict) -> int:
    return get_total_stats(player_data).get('mp', 50)


def heal_hp(player_data: dict, amount: int) -> int:
    """恢复 HP，返回实际恢复量"""
    attrs = player_data.setdefault('attributes', {})
    max_hp = get_max_hp(player_data)
    current = attrs.get('current_hp', max_hp)
    new_hp = min(max_hp, current + amount)
    actual = new_hp - current
    attrs['current_hp'] = new_hp
    return actual


def heal_mp(player_data: dict, amount: int) -> int:
    """恢复 MP，返回实际恢复量"""
    attrs = player_data.setdefault('attributes', {})
    max_mp = get_max_mp(player_data)
    current = attrs.get('current_mp', max_mp)
    new_mp = min(max_mp, current + amount)
    actual = new_mp - current
    attrs['current_mp'] = new_mp
    return actual


def ensure_attributes(player_data: dict) -> None:
    """初始化属性（如果不存在）"""
    attrs = player_data.setdefault('attributes', {})
    if 'current_hp' not in attrs:
        attrs['current_hp'] = get_max_hp(player_data)
    if 'current_mp' not in attrs:
        attrs['current_mp'] = get_max_mp(player_data)

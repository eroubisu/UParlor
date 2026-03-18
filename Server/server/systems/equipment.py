"""装备系统 — 穿脱装备、装备栏查询

装备存储: player_data['equipment'] = {slot: {id, quality} | None}
装备栏位: 来自 data/attributes.json 的 equipment_slots
物品需声明 equip_slot 才能装备
"""

from __future__ import annotations

from .items import get_item_info, inv_get, inv_add, inv_sub
from .attributes import EQUIPMENT_SLOTS


def equip_item(player_data: dict, item_id: str, quality: int = 0) -> str:
    """穿戴装备，返回结果消息"""
    info = get_item_info(item_id)
    if not info:
        return "未知物品。"

    slot = info.get('equip_slot')
    if not slot or slot not in EQUIPMENT_SLOTS:
        return "此物品无法装备。"

    inventory = player_data.get('inventory', {})
    if inv_get(inventory, item_id, quality) <= 0:
        return "你没有这个物品。"

    equipment = player_data.setdefault('equipment', {})

    # 卸下当前装备（放回背包）
    current = equipment.get(slot)
    if current and isinstance(current, dict):
        inv_add(inventory, current['id'], current.get('quality', 0))

    # 穿上新装备
    inv_sub(inventory, item_id, quality)
    equipment[slot] = {'id': item_id, 'quality': quality}

    slot_name = EQUIPMENT_SLOTS[slot]
    item_name = info.get('name', item_id)
    msg = f"已装备 {item_name} → {slot_name}"
    if current and isinstance(current, dict):
        old_info = get_item_info(current['id'])
        old_name = old_info.get('name', current['id']) if old_info else current['id']
        msg += f"（{old_name} 已放回背包）"
    return msg


def unequip_item(player_data: dict, slot: str) -> str:
    """卸下装备，返回结果消息"""
    if slot not in EQUIPMENT_SLOTS:
        return "无效的装备位。"

    equipment = player_data.get('equipment', {})
    current = equipment.get(slot)
    if not current or not isinstance(current, dict):
        return f"{EQUIPMENT_SLOTS[slot]}位没有装备。"

    inventory = player_data.setdefault('inventory', {})
    inv_add(inventory, current['id'], current.get('quality', 0))
    equipment[slot] = None

    item_info = get_item_info(current['id'])
    item_name = item_info.get('name', current['id']) if item_info else current['id']
    return f"已卸下 {item_name}。"


def get_equipped_items(player_data: dict) -> dict[str, dict | None]:
    """返回装备栏状态: {slot: {id, quality, name} | None}"""
    equipment = player_data.get('equipment', {})
    result = {}
    for slot in EQUIPMENT_SLOTS:
        entry = equipment.get(slot)
        if entry and isinstance(entry, dict):
            info = get_item_info(entry['id'])
            result[slot] = {
                'id': entry['id'],
                'quality': entry.get('quality', 0),
                'name': info.get('name', entry['id']) if info else entry['id'],
            }
        else:
            result[slot] = None
    return result

"""STATUS 消息构建 — 从 player_data 构建完整状态负载"""

from __future__ import annotations

from ..systems.titles import get_title_name
from ..systems.items import get_item_info
from ..msg_types import STATUS


def build_status_message(server, player_data: dict) -> dict:
    """构建完整 STATUS 消息，含物品栏、属性、装备、名片等。"""
    titles_data = player_data.get('titles', {})
    displayed = titles_data.get('displayed', [])
    title_display = ' | '.join(get_title_name(t) for t in displayed) if displayed else ''
    from ..systems.leveling import exp_for_level
    status_data = {
        'name': player_data['name'],
        'level': player_data['level'],
        'exp': player_data.get('exp', 0),
        'exp_to_next': exp_for_level(player_data['level']),
        'gold': player_data['gold'],
        'title': title_display,
        'accessory': player_data.get('accessory'),
        'window_layout': player_data.get('window_layout'),
    }

    # 名片
    pc = player_data.get('profile_card', {})
    pattern_id = pc.get('pattern_id', 'pattern_default')
    pattern_info = get_item_info(pattern_id) or {}
    status_data['profile_card'] = {
        'motto': pc.get('motto', ''),
        'name_color': pc.get('name_color', '#ffffff'),
        'motto_color': pc.get('motto_color', '#b3b3b3'),
        'border_color': pc.get('border_color', '#5a5a5a'),
        'pattern': pattern_info.get('pattern', {'chars': '.', 'colors': ['#505050']}),
        'pattern_id': pattern_id,
        'card_fields': pc.get('card_fields', ['level', 'gold', 'games', 'created']),
    }
    status_data['created_at'] = player_data.get('created_at', '')
    status_data['friends_count'] = len(player_data.get('friends', []))

    # 物品栏
    status_data['inventory'] = _build_inventory_list(player_data)

    # 游戏统计
    gs = player_data.get('game_stats')
    if gs:
        status_data['game_stats'] = gs

    # 属性与装备
    from ..systems.attributes import get_total_stats, get_max_hp, get_max_mp, ensure_attributes
    from ..systems.equipment import get_equipped_items
    ensure_attributes(player_data)
    attrs = player_data.get('attributes', {})
    status_data['attributes'] = {
        'stats': get_total_stats(player_data),
        'current_hp': attrs.get('current_hp', get_max_hp(player_data)),
        'max_hp': get_max_hp(player_data),
        'current_mp': attrs.get('current_mp', get_max_mp(player_data)),
        'max_mp': get_max_mp(player_data),
    }
    status_data['equipment'] = get_equipped_items(player_data)

    # 位置信息
    player_name = player_data.get('name', '')
    location = server.lobby_engine.get_player_location(player_name)
    game_id = server.lobby_engine._get_game_for_location(location)
    extras = {}
    if game_id:
        engine = server.lobby_engine._get_engine(game_id, player_name)
        if engine:
            extras = engine.get_status_extras(player_name, player_data) or {}

    status_msg = {'type': STATUS, 'data': status_data}
    status_msg['location'] = location
    status_msg['location_path'] = server.lobby_engine.get_location_path(location, player_name)
    status_msg.update(extras)
    return status_msg


def _build_inventory_list(player_data: dict) -> list[dict]:
    """从 player_data 构建客户端物品列表（含装备标记）。"""
    inv_raw = player_data.get('inventory', {})
    equipment = player_data.get('equipment', {})
    inv_list: list[dict] = []

    for item_id, val in inv_raw.items():
        info = get_item_info(item_id) or {}
        if isinstance(val, int):
            if val > 0:
                entry = _item_entry(item_id, 0, val, info)
                inv_list.append(entry)
        elif isinstance(val, dict):
            for q_str, count in sorted(val.items()):
                if isinstance(count, int) and count > 0:
                    entry = _item_entry(item_id, int(q_str), count, info)
                    inv_list.append(entry)

    for slot, slot_val in equipment.items():
        if slot_val and isinstance(slot_val, dict):
            eid = slot_val['id']
            eq = slot_val.get('quality', 0)
            einfo = get_item_info(eid) or {}
            eq_entry = _item_entry(eid, eq, 1, einfo)
            eq_entry['equipped'] = slot
            eq_entry['use_methods'] = []
            inv_list.append(eq_entry)

    return inv_list


def _item_entry(item_id: str, quality: int, count: int, info: dict) -> dict:
    entry = {
        'id': item_id,
        'quality': quality,
        'count': count,
        'name': info.get('name', item_id),
        'desc': info.get('desc', ''),
        'category': info.get('category', ''),
        'use_methods': info.get('use_methods', []),
    }
    if info.get('pattern'):
        entry['pattern'] = info['pattern']
    return entry

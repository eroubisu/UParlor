"""名片消息处理器 — get_profile_card / update_profile_card"""

from __future__ import annotations

from . import register
from ..player.manager import PlayerManager
from ..systems.titles import get_title_name
from ..systems.items import get_item_info
from ..msg_types import PROFILE_CARD


@register('get_profile_card')
def handle_get_profile_card(server, client_socket, name, player_data, msg):
    target = msg.get('target', '').strip()
    if not target or not PlayerManager.player_exists(target):
        return
    target_data = PlayerManager.load_player_data(target)
    if not target_data:
        return
    pc = target_data.get('profile_card', {})
    pattern_id = pc.get('pattern_id', 'pattern_default')
    pattern_info = get_item_info(pattern_id) or {}
    titles_data = target_data.get('titles', {})
    displayed = titles_data.get('displayed', [])
    title_display = ' | '.join(get_title_name(t) for t in displayed) if displayed else ''
    card = {
        'name': target_data.get('name', target),
        'level': target_data.get('level', 1),
        'gold': target_data.get('gold', 0),
        'title': title_display,
        'motto': pc.get('motto', ''),
        'name_color': pc.get('name_color', '#ffffff'),
        'motto_color': pc.get('motto_color', '#b3b3b3'),
        'border_color': pc.get('border_color', '#5a5a5a'),
        'pattern': pattern_info.get('pattern', {'chars': '.', 'colors': ['#505050']}),
        'card_fields': pc.get('card_fields', ['level', 'gold', 'games', 'created']),
        'created_at': target_data.get('created_at', ''),
        'game_stats': target_data.get('game_stats', {}),
        'social_stats': target_data.get('social_stats', {}),
        'friends_count': len(target_data.get('friends', [])),
    }
    server.send_to(client_socket, {'type': PROFILE_CARD, 'data': card})


@register('update_profile_card')
def handle_update_profile_card(server, client_socket, name, player_data, msg):
    updates = msg.get('data', {})
    pc = player_data.setdefault('profile_card', {})
    allowed = ('motto', 'pattern_id', 'name_color', 'motto_color', 'border_color')
    for k in allowed:
        if k in updates:
            val = updates[k]
            if isinstance(val, str) and len(val) <= 200:
                if k == 'pattern_id':
                    inv = player_data.get('inventory', {})
                    if val not in inv or (isinstance(inv.get(val), int) and inv[val] <= 0):
                        continue
                pc[k] = val
    if 'card_fields' in updates:
        valid_ids = {'level', 'gold', 'friends', 'games', 'days', 'created'}
        raw = updates['card_fields']
        if isinstance(raw, list) and len(raw) <= 4:
            filtered = [f for f in raw if isinstance(f, str) and f in valid_ids]
            pc['card_fields'] = filtered
    PlayerManager.save_player_data(name, player_data)
    server.send_player_status(client_socket, player_data)

"""名片消息处理器 — get_profile_card / update_profile_card"""

from __future__ import annotations

from . import register
from ..player.manager import PlayerManager
from ..player.schema import (
    DEFAULT_CARD_FIELDS,
    DEFAULT_NAME_COLOR, DEFAULT_MOTTO_COLOR, DEFAULT_BORDER_COLOR,
)
from ..systems.titles import get_title_name
from ..msg_types import PROFILE_CARD


@register('get_profile_card')
def handle_get_profile_card(server, client_socket, name, player_data, msg):
    target = msg.get('target', '').strip()
    if not target:
        return
    if PlayerManager.player_exists(target):
        _send_player_card(server, client_socket, target)
    else:
        _send_bot_card(server, client_socket, name, target)


def _send_bot_card(server, client_socket, requester, target):
    """尝试为游戏机器人发送简易名片"""
    lobby = server.lobby_engine
    loc = lobby.get_player_location(requester)
    gid = lobby._get_game_for_location(loc) if loc else None
    if not gid:
        return
    engine = lobby._get_engine(gid, requester)
    if not engine:
        return
    room = engine.get_player_room(requester)
    if not room or not room.is_bot(target):
        return
    card = {
        'name': target,
        'is_bot': True,
        'level': 0,
        'gold': 0,
        'title': '游戏机器人',
    }
    server.send_to(client_socket, {'type': PROFILE_CARD, 'data': card})


def _send_player_card(server, client_socket, target):
    """发送真人玩家名片"""
    target_data = PlayerManager.load_player_data(target)
    if not target_data:
        return
    pc = target_data.get('profile_card', {})
    titles_data = target_data.get('titles', {})
    displayed = titles_data.get('displayed', [])
    title_display = ' | '.join(get_title_name(t) for t in displayed) if displayed else ''
    card = {
        'name': target_data.get('name', target),
        'level': target_data.get('level', 1),
        'gold': target_data.get('gold', 0),
        'title': title_display,
        'motto': pc.get('motto', ''),
        'name_color': pc.get('name_color', DEFAULT_NAME_COLOR),
        'motto_color': pc.get('motto_color', DEFAULT_MOTTO_COLOR),
        'border_color': pc.get('border_color', DEFAULT_BORDER_COLOR),
        'card_fields': pc.get('card_fields', list(DEFAULT_CARD_FIELDS)),
        'created_at': target_data.get('created_at', ''),
        'game_stats': target_data.get('game_stats', {}),
        'friends_count': len(target_data.get('friends', [])),
    }
    server.send_to(client_socket, {'type': PROFILE_CARD, 'data': card})


@register('update_profile_card')
def handle_update_profile_card(server, client_socket, name, player_data, msg):
    updates = msg.get('data', {})
    pc = player_data.setdefault('profile_card', {})
    allowed = ('motto', 'name_color', 'motto_color', 'border_color')
    for k in allowed:
        if k in updates:
            val = updates[k]
            if isinstance(val, str) and len(val) <= 200:
                pc[k] = val
    if 'card_fields' in updates:
        valid_ids = {'level', 'gold', 'friends', 'games', 'days', 'created'}
        raw = updates['card_fields']
        if isinstance(raw, list) and len(raw) <= 4:
            filtered = [f for f in raw if isinstance(f, str) and f in valid_ids]
            pc['card_fields'] = filtered
    PlayerManager.save_player_data(name, player_data)
    server.send_player_status(client_socket, player_data)

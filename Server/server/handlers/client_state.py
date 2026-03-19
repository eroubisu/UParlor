"""客户端状态消息处理器 — viewport / save_layout / ai_sync_up / ai_gift_consume / unequip / delete_account"""

from __future__ import annotations

from . import register
from ..player.manager import PlayerManager
from ..msg_types import ACTION, GAME, LOGIN_PROMPT


@register('viewport')
def handle_viewport(server, client_socket, name, player_data, msg):
    w = msg.get('w', 0)
    h = msg.get('h', 0)
    if not (isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0):
        return
    with server.lock:
        server.clients[client_socket]['viewport'] = (w, h)
    # 仅当玩家在 world 游戏中时才更新视口并刷新地图
    lobby = server.lobby_engine
    location = lobby.get_player_location(name)
    game_id = lobby._get_game_for_location(location)
    if game_id == 'world':
        engine = lobby._get_engine('world', name)
        if engine and hasattr(engine, 'set_viewport'):
            engine.set_viewport(name, w, h)
            room_data = engine.get_player_room_data(name)
            if room_data:
                from ..msg_types import ROOM_UPDATE
                server.send_to(client_socket, {'type': ROOM_UPDATE, 'room_data': room_data})


@register('save_layout')
def handle_save_layout(server, client_socket, name, player_data, msg):
    layout = msg.get('layout')
    if isinstance(layout, dict):
        if server.lobby_engine._validate_layout(layout):
            player_data['window_layout'] = layout
            PlayerManager.save_player_data(name, player_data)


@register('ai_sync_up')
def handle_ai_sync_up(server, client_socket, name, player_data, msg):
    companions = msg.get('companions')
    if isinstance(companions, dict):
        player_data['ai_companions'] = companions
    token_stats = msg.get('token_stats')
    if isinstance(token_stats, dict):
        saved = player_data.get('ai_token_stats', {})
        if token_stats.get('today') == saved.get('today', ''):
            r_models = token_stats.get('models', {})
            s_models = saved.get('models', {})
            merged = {}
            for k in set(r_models) | set(s_models):
                merged[k] = max(r_models.get(k, 0), s_models.get(k, 0))
            token_stats['models'] = merged
        player_data['ai_token_stats'] = token_stats
    PlayerManager.save_player_data(name, player_data)


@register('ai_gift_consume')
def handle_ai_gift_consume(server, client_socket, name, player_data, msg):
    item_id = msg.get('item_id', '')
    qty = msg.get('qty', 1)
    quality = msg.get('quality', 0)
    if not (isinstance(item_id, str) and item_id and isinstance(qty, int) and 0 < qty <= 99):
        return
    from ..systems.items import inv_get, inv_sub
    inventory = player_data.get('inventory', {})
    cur = inv_get(inventory, item_id, quality)
    if cur >= qty:
        inv_sub(inventory, item_id, quality, qty)
        PlayerManager.save_player_data(name, player_data)
        server.send_player_status(client_socket, player_data)


@register('unequip')
def handle_unequip(server, client_socket, name, player_data, msg):
    slot = msg.get('slot', '').strip()
    if not slot:
        return
    from ..systems.equipment import unequip_item, EQUIPMENT_SLOTS
    if slot in EQUIPMENT_SLOTS:
        result = unequip_item(player_data, slot)
        PlayerManager.save_player_data(name, player_data)
        server.send_to(client_socket, {'type': GAME, 'text': result})
        server.send_player_status(client_socket, player_data)


@register('delete_account')
def handle_delete_account(server, client_socket, name, player_data, msg):
    password = msg.get('password', '')
    if not isinstance(password, str) or not password:
        server.send_to(client_socket, {'type': GAME, 'text': '密码不能为空。'})
        return
    from ..lobby.account import do_delete_account
    result = do_delete_account(server.lobby_engine, name, password)
    if isinstance(result, dict) and result.get('action') == 'account_deleted':
        server.send_to(client_socket, {'type': GAME, 'text': result.get('message', '')})
        with server.lock:
            server.clients[client_socket]['state'] = 'login'
            server.clients[client_socket]['name'] = None
            server.clients[client_socket]['data'] = None
        server.broadcast_online_users()
        server.send_to(client_socket, {'type': ACTION, 'action': 'return_to_login'})
        server.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '请输入用户名：'})
    else:
        server.send_to(client_socket, {
            'type': GAME,
            'text': result if isinstance(result, str) else '删除失败。',
        })

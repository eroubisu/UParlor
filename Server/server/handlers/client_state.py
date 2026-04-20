"""客户端状态消息处理器 — viewport / save_layout / delete_account"""

from __future__ import annotations

from . import register
from ..player.manager import PlayerManager
from ..msg_types import ACTION, GAME, LOGIN_PROMPT, ONLINE_USERS, ROOM_LIST


@register('viewport')
def handle_viewport(server, client_socket, name, player_data, msg):
    from ..config import MAX_VIEWPORT_WIDTH, MAX_VIEWPORT_HEIGHT
    w = msg.get('w', 0)
    h = msg.get('h', 0)
    if not (isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0):
        return
    w = min(w, MAX_VIEWPORT_WIDTH)
    h = min(h, MAX_VIEWPORT_HEIGHT)
    with server.lock:
        server.clients[client_socket]['viewport'] = (w, h)


@register('save_layout')
def handle_save_layout(server, client_socket, name, player_data, msg):
    layout = msg.get('layout')
    if isinstance(layout, dict):
        if server.lobby_engine._validate_layout(layout):
            player_data['window_layout'] = layout
            PlayerManager.save_player_data(name, player_data)


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


@register('get_room_list')
def handle_get_room_list(server, client_socket, name, player_data, msg):
    rooms = server.lobby_engine.get_all_rooms()
    server.send_to(client_socket, {'type': ROOM_LIST, 'rooms': rooms})


@register('get_online_users')
def handle_get_online_users(server, client_socket, name, player_data, msg):
    users = server._collect_online_users()
    server.send_to(client_socket, {'type': ONLINE_USERS, 'users': users})

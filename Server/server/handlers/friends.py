"""好友系统消息处理器 — friend_request / friend_accept / friend_reject / friend_remove"""

from __future__ import annotations

from . import register
from ..player.manager import PlayerManager
from ..msg_types import FRIEND_REQUEST, SYSTEM


@register('friend_request')
def handle_friend_request(server, client_socket, name, player_data, msg):
    target = msg.get('name', '').strip()
    if not target or target == name or not PlayerManager.player_exists(target):
        return
    friends = player_data.get('friends', [])
    if target in friends:
        return
    target_data = PlayerManager.load_player_data(target)
    if not target_data:
        return
    pending = target_data.setdefault('pending_friend_requests', [])
    if name not in pending:
        pending.append(name)
        PlayerManager.save_player_data(target, target_data)
    with server.lock:
        for client, info in server.clients.items():
            if info.get('name') == target and info.get('state') == 'playing':
                info['data'].setdefault('pending_friend_requests', [])
                if name not in info['data']['pending_friend_requests']:
                    info['data']['pending_friend_requests'].append(name)
                server.send_to(client, {
                    'type': FRIEND_REQUEST,
                    'from': name,
                    'pending': info['data'].get('pending_friend_requests', []),
                })


@register('friend_accept')
def handle_friend_accept(server, client_socket, name, player_data, msg):
    target = msg.get('name', '').strip()
    if not target or target == name:
        return
    pending = player_data.get('pending_friend_requests', [])
    if target in pending:
        pending.remove(target)
        friends = player_data.setdefault('friends', [])
        if target not in friends:
            friends.append(target)
        PlayerManager.save_player_data(name, player_data)
        target_data = PlayerManager.load_player_data(target)
        if target_data:
            t_friends = target_data.setdefault('friends', [])
            if name not in t_friends:
                t_friends.append(name)
                PlayerManager.save_player_data(target, target_data)
            with server.lock:
                for client, info in server.clients.items():
                    if info.get('name') == target and info.get('state') == 'playing':
                        info['data']['friends'] = list(target_data.get('friends', []))
                        server._send_friend_list(client, info['data'])
                        server.send_to(client, {
                            'type': SYSTEM,
                            'text': f'{name} 已接受你的好友申请',
                        })
    server._send_friend_list(client_socket, player_data)
    server.send_to(client_socket, {
        'type': FRIEND_REQUEST,
        'pending': player_data.get('pending_friend_requests', []),
    })


@register('friend_reject')
def handle_friend_reject(server, client_socket, name, player_data, msg):
    target = msg.get('name', '').strip()
    if not target:
        return
    pending = player_data.get('pending_friend_requests', [])
    if target in pending:
        pending.remove(target)
        PlayerManager.save_player_data(name, player_data)
    server.send_to(client_socket, {
        'type': FRIEND_REQUEST,
        'pending': player_data.get('pending_friend_requests', []),
    })


@register('friend_remove')
def handle_friend_remove(server, client_socket, name, player_data, msg):
    target = msg.get('name', '').strip()
    friends = player_data.get('friends', [])
    if target in friends:
        friends.remove(target)
        PlayerManager.save_player_data(name, player_data)
        target_data = PlayerManager.load_player_data(target)
        if target_data:
            t_friends = target_data.get('friends', [])
            if name in t_friends:
                t_friends.remove(name)
                PlayerManager.save_player_data(target, target_data)
            with server.lock:
                for client, info in server.clients.items():
                    if info.get('name') == target and info.get('state') == 'playing':
                        info['data']['friends'] = list(target_data.get('friends', []))
                        server._send_friend_list(client, info['data'])
                        server.send_to(client, {
                            'type': SYSTEM,
                            'text': f'{name} 已将你从好友列表移除',
                        })
    server._send_friend_list(client_socket, player_data)

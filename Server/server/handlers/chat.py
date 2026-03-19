"""聊天消息处理器 — chat / private_chat"""

from __future__ import annotations

from datetime import datetime

from . import register
from ..storage import maintenance
from ..msg_types import CHAT, PRIVATE_CHAT, SYSTEM


@register('chat')
def handle_chat(server, client_socket, name, player_data, msg):
    text = msg.get('text', '').strip()
    if not text:
        return
    channel = msg.get('channel', 1)
    display_name = f"[{player_data['level']}]{name}"
    maintenance.track_chat_message(name, player_data)
    server.log_mgr.save(channel, display_name, text)
    current_time = datetime.now().strftime('%H:%M')
    chat_msg = {
        'type': CHAT,
        'name': display_name,
        'text': text,
        'channel': channel,
        'time': current_time,
    }
    server.broadcast(chat_msg, channel=channel)
    print(f"[CH{channel}][{name}] {text}")


@register('private_chat')
def handle_private_chat(server, client_socket, name, player_data, msg):
    target = msg.get('target', '').strip()
    text = msg.get('text', '').strip()
    if not target or not text:
        return
    friends = player_data.get('friends', [])
    if target not in friends:
        server.send_to(client_socket, {
            'type': SYSTEM,
            'text': '只能向好友发送私聊消息。',
        })
        return
    display_name = f"[{player_data['level']}]{name}"
    current_time = datetime.now().strftime('%H:%M')
    dm_msg = {
        'type': PRIVATE_CHAT,
        'from': name,
        'from_display': display_name,
        'to': target,
        'text': text,
        'time': current_time,
    }
    server.dm_log_mgr.save(name, target, text)
    with server.lock:
        for client, info in server.clients.items():
            cname = info.get('name')
            if info.get('state') != 'playing':
                continue
            if cname in (target, name):
                server.send_to(client, dm_msg)
    print(f"[DM][{name} \u2192 {target}] {text}")

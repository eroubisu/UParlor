"""聊天消息处理器 — chat / private_chat"""

from __future__ import annotations

import logging
from datetime import datetime

from . import register
from ..msg_types import CHAT, DM_HISTORY, PRIVATE_CHAT, SYSTEM, ROOM_CHAT

logger = logging.getLogger(__name__)


_MAX_MSG_LEN = 500


@register('chat')
def handle_chat(server, client_socket, name, player_data, msg):
    text = msg.get('text', '').strip()[:_MAX_MSG_LEN]
    if not text:
        return
    channel = msg.get('channel', 1)
    display_name = f"[{player_data['level']}]{name}"
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
    logger.info("[CH%d][%s] %s", channel, name, text)


@register('private_chat')
def handle_private_chat(server, client_socket, name, player_data, msg):
    target = msg.get('target', '').strip()
    text = msg.get('text', '').strip()[:_MAX_MSG_LEN]
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
    # 发给双方（发送者 + 接收者）
    server.send_to(client_socket, dm_msg)
    if target != name:
        server.send_to_player(target, dm_msg)
    logger.info("[DM][%s → %s] %s", name, target, text)


@register('room_chat')
def handle_room_chat(server, client_socket, name, player_data, msg):
    text = msg.get('text', '').strip()[:_MAX_MSG_LEN]
    if not text:
        return
    room = server.lobby_engine.get_player_room_data(name)
    if not room:
        server.send_to(client_socket, {
            'type': SYSTEM, 'text': '你不在任何房间中。',
        })
        return
    players = room.get('players', [])
    display_name = f"[{player_data['level']}]{name}"
    current_time = datetime.now().strftime('%H:%M')
    chat_msg = {
        'type': ROOM_CHAT,
        'name': display_name,
        'from': name,
        'text': text,
        'time': current_time,
    }
    for p in players:
        server.send_to_player(p, chat_msg)
    logger.info("[ROOM][%s] %s", name, text)


@register('clear_dm_history')
def handle_clear_dm_history(server, client_socket, name, player_data, msg):
    """清空与指定玩家的私聊记录"""
    target = msg.get('target', '').strip()
    if not target:
        return
    server.dm_log_mgr.clear_history(name, target)
    server.send_to(client_socket, {
        'type': SYSTEM, 'text': f'已清空与 {target} 的聊天记录',
    })
    logger.info("[DM] %s 清空了与 %s 的聊天记录", name, target)


@register('get_dm_history')
def handle_get_dm_history(server, client_socket, name, player_data, msg):
    """按需加载单个 peer 的私聊历史"""
    target = msg.get('target', '').strip()
    if not target:
        return
    msgs = server.dm_log_mgr.get_history(name, target, limit=50)
    conversations = {target: [
        {'from': m['from'], 'text': m['text'], 'time': m.get('time', '')}
        for m in msgs
    ]}
    server.send_to(client_socket, {
        'type': DM_HISTORY,
        'conversations': conversations,
    })

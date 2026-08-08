"""聊天消息处理器 — chat / private_chat"""

from __future__ import annotations

import logging

from . import register
from ..msg_types import DM_HISTORY, SYSTEM, ROOM_CHAT
from ..player.chat_style import build_chat_sender, enrich_chat_messages
from ..storage.chat_log import get_beijing_now

logger = logging.getLogger(__name__)


_MAX_MSG_LEN = 500


@register('chat')
def handle_chat(server, client_socket, name, player_data, msg):
    text = msg.get('text', '').strip()[:_MAX_MSG_LEN]
    if not text:
        return
    channel = msg.get('channel', 1)
    saved = server.log_mgr.save(channel, name, text)
    if saved is None:
        server.send_to(client_socket, {
            'type': SYSTEM,
            'text': '聊天记录保存失败，请稍后重试。',
        })
        logger.error("[CH%d][%s] 消息保存失败，未广播", channel, name)
        return
    chat_msg = dict(saved)
    chat_msg['sender'] = build_chat_sender(player_data, name)
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
    saved = server.dm_log_mgr.save(name, target, text)
    dm_msg = dict(saved)
    dm_msg['sender'] = build_chat_sender(player_data, name)
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
    current_time = get_beijing_now().strftime('%H:%M:%S')
    chat_msg = {
        'type': ROOM_CHAT,
        'name': name,
        'from': name,
        'text': text,
        'time': current_time,
        'sender': build_chat_sender(player_data, name),
    }
    for p in players:
        server.send_to_player(p, chat_msg)
    logger.info("[ROOM][%s] %s", name, text)


@register('get_dm_history')
def handle_get_dm_history(server, client_socket, name, player_data, msg):
    """按需加载单个 peer 的私聊历史"""
    del player_data
    target = msg.get('target', '').strip()
    if not target:
        return
    msgs = server.dm_log_mgr.get_history(name, target, limit=50)
    conversations = {target: enrich_chat_messages(
        [
            {'from': m['from'], 'to': m.get('to', ''),
             'text': m['text'], 'time': m.get('time', '')}
            for m in msgs
        ],
        sender_field='from',
    )}
    server.send_to(client_socket, {
        'type': DM_HISTORY,
        'conversations': conversations,
    })


@register('get_chat_history')
def handle_get_chat_history(server, client_socket, name, player_data, msg):
    """Load the preceding world-chat page requested by the player."""
    del name, player_data
    server._send_chat_history(
        client_socket,
        1,
        before_id=str(msg.get('before_id', '')),
        after_id=str(msg.get('after_id', '')),
        prepend=True,
    )

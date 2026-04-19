"""房间消息处理器 — join_room"""

from __future__ import annotations

from . import register
from ..msg_types import SYSTEM


@register('join_room')
def handle_join_room(server, client_socket, name, player_data, msg):
    """通过房间号加入房间"""
    room_id = msg.get('room_id', '').strip()
    if not room_id:
        return

    lobby = server.lobby_engine
    for engine in lobby.game_engines.values():
        rooms = getattr(engine, '_rooms', {})
        if room_id in rooms:
            result = engine.handle_command(
                lobby, name, player_data, '/join', room_id)
            if result:
                from ..core.result_dispatcher import dispatch_result
                dispatch_result(server, client_socket, name, player_data, result)
            return

    server.send_to(client_socket, {'type': SYSTEM, 'text': '房间不存在或已关闭。'})

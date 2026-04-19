"""游戏邀请消息处理器 — game_invite_accept / game_invite_reject"""

from __future__ import annotations

from . import register
from ..msg_types import SYSTEM, GAME_INVITE_RESULT


@register('game_invite_accept')
def handle_game_invite_accept(server, client_socket, name, player_data, msg):
    """接受游戏邀请"""
    game = msg.get('game', '')
    from_name = msg.get('from', '')
    if not game:
        return

    lobby = server.lobby_engine
    engine = lobby._ensure_engine(game, name)
    if not engine:
        server.send_to(client_socket, {
            'type': SYSTEM,
            'text': '游戏引擎不可用。',
        })
        return

    invite = engine._invites.get(name)
    if not invite:
        server.send_to(client_socket, {
            'type': GAME_INVITE_RESULT,
            'game': game, 'from': from_name, 'status': 'expired',
        })
        return

    result = engine.handle_command(lobby, name, player_data, '/accept', '')
    if result:
        from ..core.result_dispatcher import dispatch_result
        dispatch_result(server, client_socket, name, player_data, result)
        server.send_to(client_socket, {
            'type': GAME_INVITE_RESULT,
            'game': game, 'from': from_name, 'status': 'accepted',
        })
    else:
        server.send_to(client_socket, {
            'type': SYSTEM, 'text': '接受邀请失败，房间可能已不可用。',
        })
        server.send_to(client_socket, {
            'type': GAME_INVITE_RESULT,
            'game': game, 'from': from_name, 'status': 'expired',
        })


@register('game_invite_reject')
def handle_game_invite_reject(server, client_socket, name, player_data, msg):
    """拒绝游戏邀请"""
    game = msg.get('game', '')
    if not game:
        return

    lobby = server.lobby_engine
    engine = lobby._get_engine(game, name)
    if engine:
        invite = engine._invites.pop(name, None)
        if invite:
            inviter = invite.get('from', '')
            server.send_to(client_socket, {
                'type': GAME_INVITE_RESULT,
                'game': game, 'from': inviter, 'status': 'rejected',
            })
            if inviter:
                server.send_to_player(inviter, {
                    'type': SYSTEM,
                    'text': f'{name} 拒绝了你的游戏邀请。',
                })

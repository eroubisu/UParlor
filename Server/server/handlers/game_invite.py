"""游戏邀请消息处理器 — game_invite_accept / game_invite_reject"""

from __future__ import annotations

from . import register
from ..msg_types import SYSTEM, GAME_INVITE_RESULT


@register('game_invite_accept')
def handle_game_invite_accept(server, client_socket, name, player_data, msg):
    """接受游戏邀请 — 玩家必须身处对应游戏大厅"""
    game = msg.get('game', '')
    from_name = msg.get('from', '')
    if not game:
        return

    lobby = server.lobby_engine
    location = lobby.get_player_location(name)
    expected = f'{game}_lobby'

    if location != expected:
        from ..games import GAMES
        mod = GAMES.get(game)
        game_name = game
        if mod:
            info = getattr(mod, 'GAME_INFO', {})
            locs = info.get('locations', {})
            loc_info = locs.get(expected)
            if loc_info:
                game_name = loc_info[0]
        server.send_to(client_socket, {
            'type': SYSTEM,
            'text': f'请先进入{game_name}大厅再接受邀请',
        })
        return

    engine = lobby._get_engine(game, name)
    if not engine:
        server.send_to(client_socket, {
            'type': SYSTEM,
            'text': '游戏引擎不可用。',
        })
        return

    invite = engine.get_invite(name)
    if not invite:
        server.send_to(client_socket, {
            'type': GAME_INVITE_RESULT,
            'game': game, 'from': from_name, 'status': 'expired',
        })
        return

    result = lobby.process_command(player_data, '/accept')
    if result:
        from ..game_core.result_dispatcher import dispatch_result
        dispatch_result(server, client_socket, name, player_data, result)
        server.send_to(client_socket, {
            'type': GAME_INVITE_RESULT,
            'game': game, 'from': from_name, 'status': 'accepted',
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
        engine.clear_invite(name)

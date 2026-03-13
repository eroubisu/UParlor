"""Rich Result Protocol 分发器 — 从 chat_server.py 提取"""

from __future__ import annotations
from typing import Callable

from .player_manager import PlayerManager


# ══════════════════════════════════════════════════
#  大厅级 action 注册表
# ══════════════════════════════════════════════════

# handler 签名: (server, client_socket, name, player_data, result) -> None
ActionHandler = Callable[..., None]
_ACTION_HANDLERS: dict[str, ActionHandler] = {}


def register_action(action_name: str, handler: ActionHandler) -> None:
    """注册大厅级 action 处理器。"""
    _ACTION_HANDLERS[action_name] = handler


def _action_clear(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {'type': 'action', 'action': 'clear'})


def _action_version(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {
        'type': 'action', 'action': 'version',
        'server_version': result.get('server_version', '未知')})


def _action_confirm_prompt(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {
        'type': 'game', 'text': result.get('message', '')})


def _action_exit(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {'type': 'action', 'action': 'exit'})
    PlayerManager.save_player_data(name, player_data)


def _action_rename_success(server, client_socket, name, player_data, result):
    old_name = result.get('old_name')
    new_name = result.get('new_name')
    server.clients[client_socket]['name'] = new_name
    server.send_to(client_socket, {'type': 'game', 'text': result.get('message', '')})
    PlayerManager.save_player_data(new_name, player_data)
    server.send_player_status(client_socket, player_data)
    server.broadcast({'type': 'chat', 'name': '[SYS]',
                      'text': f'{old_name} 改名为 {new_name}', 'channel': 1})


def _action_account_deleted(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {'type': 'game', 'text': result.get('message', '')})
    server.send_to(client_socket, {'type': 'action', 'action': 'exit'})


register_action('clear', _action_clear)
register_action('version', _action_version)
register_action('confirm_prompt', _action_confirm_prompt)
register_action('exit', _action_exit)
register_action('rename_success', _action_rename_success)
register_action('account_deleted', _action_account_deleted)


# 框架级消息类型 — 客户端核心直接处理，不包装
_FRAMEWORK_MSG_TYPES = frozenset({
    'game', 'room_update', 'location_update', 'room_leave', 'game_quit',
    'status', 'online_users', 'chat', 'system', 'action',
    'login_prompt', 'login_success', 'chat_history',
    'game_invite', 'game_event',
})


def wrap_game_event(msg, game_type):
    """将游戏特有消息自动包装为 game_event 信封。

    框架级消息（room_update/game/location_update 等）直接透传，
    游戏特有消息（hand_update/action_prompt/win_animation 等）包装为：
    {'type': 'game_event', 'game_type': ..., 'event': ..., 'data': {...}}
    """
    if not isinstance(msg, dict):
        return msg
    t = msg.get('type', '')
    if not t or t in _FRAMEWORK_MSG_TYPES:
        return msg
    data = {k: v for k, v in msg.items() if k != 'type'}
    return {'type': 'game_event', 'game_type': game_type, 'event': t, 'data': data}


def resolve_game_type(server, caller_name):
    """从玩家位置推断当前游戏类型"""
    if not caller_name:
        return ''
    loc = server.lobby_engine.get_player_location(caller_name)
    gid = server.lobby_engine._get_game_for_location(loc)
    return gid or ''


def inject_location_path(msg, lobby_engine, player_data=None):
    """为 location_update/room_leave 消息注入面包屑路径和指令列表"""
    if isinstance(msg, dict) and msg.get('type') in ('location_update', 'room_leave'):
        loc = msg.get('location')
        if loc:
            if 'location_path' not in msg:
                msg['location_path'] = lobby_engine.get_location_path(loc)
            if 'commands' not in msg:
                msg['commands'] = lobby_engine.get_commands_for_location(loc, player_data)


def resolve_location(lobby_engine, name, result):
    """从 result 或 lobby 获取当前位置和面包屑"""
    loc = result.get('location') if isinstance(result, dict) else None
    if not loc:
        loc = lobby_engine.get_player_location(name)
    path = lobby_engine.get_location_path(loc, name) if loc else None
    return loc, path


def _send_location_change(server, client_socket, name, player_data, action, result):
    """位置变更时发送 location_update / room_leave 消息"""
    lobby = server.lobby_engine
    if action == 'back_to_game':
        loc, path = resolve_location(lobby, name, result)
        loc_msg = {'type': 'room_leave', 'location': loc, 'location_path': path}
        inject_location_path(loc_msg, lobby, player_data)
        server.send_to(client_socket, loc_msg)
    elif action == 'location_update' or (isinstance(result, dict) and 'location' in result):
        loc, path = resolve_location(lobby, name, result)
        loc_msg = {'type': 'location_update', 'location': loc, 'location_path': path}
        inject_location_path(loc_msg, lobby, player_data)
        server.send_to(client_socket, loc_msg)


def _save_and_status(server, client_socket, name, player_data):
    """保存玩家数据并下发状态更新"""
    PlayerManager.save_player_data(name, player_data)
    if client_socket:
        server.send_player_status(client_socket, player_data)


def _refresh_caller_commands(server, client_socket, name, player_data):
    """为 caller 重新下发当前位置的指令列表"""
    lobby = server.lobby_engine
    loc = lobby.get_player_location(name)
    cmds = lobby.get_commands_for_location(loc, player_data)
    server.send_to(client_socket, {'type': 'commands_update', 'commands': cmds})


def dispatch_game_result(server, result, caller_socket=None, caller_name=None, caller_data=None):
    """通用游戏结果分发器 — Rich Result Protocol。

    游戏引擎返回 send_to_caller / send_to_players / schedule / save，
    本方法只做无脑投递，不解读游戏内容。
    游戏特有消息类型自动包装为 game_event 信封。
    """
    action = result.get('action', '') if isinstance(result, dict) else ''
    game_type = resolve_game_type(server, caller_name)
    lobby = server.lobby_engine

    # 1. send_to_caller
    if caller_socket:
        for msg in result.get('send_to_caller', []):
            msg = wrap_game_event(msg, game_type)
            inject_location_path(msg, lobby, caller_data)
            server.send_to(caller_socket, msg)

    # 2. send_to_players
    for target, messages in result.get('send_to_players', {}).items():
        target_data = server._get_player_data(target)
        for msg in messages:
            msg = wrap_game_event(msg, game_type)
            inject_location_path(msg, lobby, target_data)
            server.send_to_player(target, msg)

    # 3. 位置变更：自动向 caller 发送 location_update / room_leave
    if caller_socket and caller_name and action in ('location_update', 'back_to_game'):
        _send_location_change(server, caller_socket, caller_name, caller_data, action, result)

    # 4. schedule
    for task in result.get('schedule', []):
        gid = task.get('game_id', '')
        sched = server.bot_schedulers.get(gid)
        if sched and hasattr(sched, 'handle_schedule'):
            sched.handle_schedule(task)

    # 5. save / status
    if caller_name and caller_data:
        _save_and_status(server, caller_socket, name=caller_name, player_data=caller_data)

    # 6. refresh_commands: 为所有涉及玩家重新下发指令列表
    if result.get('refresh_commands'):
        refreshed = set()
        for target in result.get('send_to_players', {}):
            target_data = server._get_player_data(target)
            if target_data:
                loc = lobby.get_player_location(target)
                cmds = lobby.get_commands_for_location(loc, target_data)
                server.send_to_player(target, {'type': 'commands_update', 'commands': cmds})
                refreshed.add(target)
        if caller_name and caller_name not in refreshed and caller_socket:
            _refresh_caller_commands(server, caller_socket, caller_name, caller_data)


def handle_simple_result(server, client_socket, name, player_data, result):
    """处理不含 send_to_caller/send_to_players 的简单游戏结果"""
    action = result.get('action', '')

    if result.get('message'):
        server.send_to(client_socket, {'type': 'game', 'text': result['message']})
    for evt in result.get('game_events', []):
        server.send_to(client_socket, evt)
    if 'room_data' in result:
        server.send_to(client_socket, {'type': 'room_update', 'room_data': result['room_data']})

    _send_location_change(server, client_socket, name, player_data, action, result)
    _save_and_status(server, client_socket, name, player_data)

    if result.get('refresh_commands'):
        _refresh_caller_commands(server, client_socket, name, player_data)


def dispatch_result(server, client_socket, name, player_data, result):
    """分发 lobby_engine.process_command 的结果"""
    if isinstance(result, dict) and 'action' in result:
        action = result['action']

        # ── 大厅级动作（注册表驱动） ──
        handler = _ACTION_HANDLERS.get(action)
        if handler is not None:
            handler(server, client_socket, name, player_data, result)

        # ── 通用游戏动作分发 ──
        else:
            if 'send_to_caller' in result or 'send_to_players' in result:
                dispatch_game_result(server, result, client_socket, name, player_data)
            else:
                handle_simple_result(server, client_socket, name, player_data, result)
    else:
        server.send_to(client_socket, {'type': 'game', 'text': result})
        PlayerManager.save_player_data(name, player_data)
        server.send_player_status(client_socket, player_data)

"""Rich Result Protocol 分发器 — 从 chat_server.py 提取"""

from __future__ import annotations
from typing import Callable

from ..player.manager import PlayerManager
from ..msg_types import (
    ACTION, CHAT, CHAT_HISTORY, FRIEND_REQUEST, GAME, GAME_EVENT, GAME_INVITE,
    LOGIN_PROMPT, LOGIN_SUCCESS, LOCATION_UPDATE, COMMANDS_UPDATE,
    ONLINE_USERS, ROOM_LIST, ROOM_UPDATE, ROOM_LEAVE, STATUS, SYSTEM,
)


# ── 大厅级 action 注册表 ──

# handler 签名: (server, client_socket, name, player_data, result) -> None
ActionHandler = Callable[..., None]
_ACTION_HANDLERS: dict[str, ActionHandler] = {}


def register_action(action_name: str):
    """装饰器：注册大厅级 action 处理器。"""
    def decorator(fn: ActionHandler) -> ActionHandler:
        _ACTION_HANDLERS[action_name] = fn
        return fn
    return decorator


@register_action('clear')
def _action_clear(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {'type': ACTION, 'action': 'clear'})


@register_action('version')
def _action_version(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {
        'type': ACTION, 'action': 'version',
        'server_version': result.get('server_version', '未知')})


@register_action('confirm_prompt')
def _action_confirm_prompt(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {
        'type': GAME, 'text': result.get('message', '')})


@register_action('exit')
def _action_exit(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {'type': ACTION, 'action': 'exit'})
    PlayerManager.save_player_data(name, player_data)


@register_action('rename_success')
def _action_rename_success(server, client_socket, name, player_data, result):
    old_name = result.get('old_name')
    new_name = result.get('new_name')
    server.clients[client_socket]['name'] = new_name
    server._unregister_player_socket(old_name)
    server._register_player_socket(new_name, client_socket)
    server.send_to(client_socket, {'type': GAME, 'text': result.get('message', '')})
    PlayerManager.save_player_data(new_name, player_data)
    server.send_player_status(client_socket, player_data)
    server.broadcast({'type': CHAT, 'name': '[SYS]',
                      'text': f'{old_name} 改名为 {new_name}', 'channel': 1})


@register_action('account_deleted')
def _action_account_deleted(server, client_socket, name, player_data, result):
    server.send_to(client_socket, {'type': GAME, 'text': result.get('message', '')})
    server.send_to(client_socket, {'type': ACTION, 'action': 'exit'})


@register_action('firework')
def _action_firework(server, client_socket, name, player_data, result):
    for msg in result.get('send_to_caller', []):
        server.send_to(client_socket, msg)
    broadcast_text = result.get('broadcast', '')
    if broadcast_text:
        server.broadcast({'type': CHAT, 'name': '[SYS]', 'text': broadcast_text, 'channel': 1})
    PlayerManager.save_player_data(name, player_data)
    server.send_player_status(client_socket, player_data)


@register_action('gift_success')
def _action_gift_success(server, client_socket, name, player_data, result):
    """赠送成功 — 通知发送者和接收者"""
    server.send_to(client_socket, {'type': GAME, 'text': result.get('message', '')})
    PlayerManager.save_player_data(name, player_data)
    server.send_player_status(client_socket, player_data)
    # 通知接收者刷新物品栏
    target_name = result.get('target_name', '')
    item_name = result.get('item_name', '')
    if target_name:
        # 发送文字提示
        server.send_to_player(target_name, {
            'type': GAME, 'text': f"你收到了 {name} 赠送的 {item_name} x1！"})
        # 让接收者客户端刷新状态（物品栏）
        cs = server._name_to_socket.get(target_name)
        if cs:
            info = server.clients.get(cs)
            if info and info.get('state') == 'playing':
                target_data = info.get('data')
                if target_data:
                    # 同步磁盘数据到内存
                    fresh = PlayerManager.load_player_data(target_name)
                    if fresh:
                        target_data['inventory'] = fresh.get('inventory', {})
                        server.send_player_status(cs, target_data)


@register_action('friend_request')
def _action_friend_request(server, client_socket, name, player_data, result):
    """游戏内发送好友申请"""
    target = result.get('target', '')
    message = result.get('message', '')
    if target and target != name and PlayerManager.player_exists(target):
        friends = player_data.get('friends', [])
        if target not in friends:
            target_data = PlayerManager.load_player_data(target)
            if target_data:
                pending = target_data.setdefault('pending_friend_requests', [])
                if name not in pending:
                    pending.append(name)
                    PlayerManager.save_player_data(target, target_data)
                cs = server._name_to_socket.get(target)
                if cs:
                    info = server.clients.get(cs)
                    if info and info.get('state') == 'playing':
                        info['data'].setdefault('pending_friend_requests', [])
                        if name not in info['data']['pending_friend_requests']:
                            info['data']['pending_friend_requests'].append(name)
                        server.send_to(cs, {
                            'type': FRIEND_REQUEST,
                            'from': name,
                            'pending': info['data'].get('pending_friend_requests', []),
                        })
    if message:
        server.send_to(client_socket, {'type': GAME, 'text': message})


# 框架级消息类型 — 客户端核心直接处理，不包装
_FRAMEWORK_MSG_TYPES = frozenset({
    GAME, ROOM_UPDATE, LOCATION_UPDATE, ROOM_LEAVE, 'game_quit',
    STATUS, ONLINE_USERS, CHAT, SYSTEM, ACTION,
    LOGIN_PROMPT, LOGIN_SUCCESS, CHAT_HISTORY,
    GAME_INVITE, GAME_EVENT, COMMANDS_UPDATE,
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
    return {'type': GAME_EVENT, 'game_type': game_type, 'event': t, 'data': data}


def resolve_game_type(server, caller_name):
    """从玩家位置推断当前游戏类型"""
    if not caller_name:
        return ''
    loc = server.lobby_engine.get_player_location(caller_name)
    gid = server.lobby_engine._get_game_for_location(loc)
    return gid or ''


def inject_location_path(msg, lobby_engine, player_data=None):
    """为 location_update/room_leave 消息注入面包屑路径和指令列表"""
    if isinstance(msg, dict) and msg.get('type') in (LOCATION_UPDATE, ROOM_LEAVE):
        loc = msg.get('location')
        if loc:
            if 'location_path' not in msg:
                name = player_data.get('name') if player_data else None
                msg['location_path'] = lobby_engine.get_location_path(loc, name)
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
        loc_msg = {'type': ROOM_LEAVE, 'location': loc, 'location_path': path}
        inject_location_path(loc_msg, lobby, player_data)
        server.send_to(client_socket, loc_msg)
    elif action == 'location_update' or (isinstance(result, dict) and 'location' in result):
        loc, path = resolve_location(lobby, name, result)
        loc_msg = {'type': LOCATION_UPDATE, 'location': loc, 'location_path': path}
        inject_location_path(loc_msg, lobby, player_data)
        server.send_to(client_socket, loc_msg)


def _save_and_status(server, client_socket, name, player_data):
    """保存玩家数据并下发状态更新"""
    PlayerManager.save_player_data(name, player_data)
    if client_socket:
        server.send_player_status(client_socket, player_data)


def _send_status_to_player(server, player_name, player_data):
    """通过玩家名查找 socket 并下发状态更新 — O(1)"""
    cs = server._name_to_socket.get(player_name)
    if cs:
        server.send_player_status(cs, player_data)


def _refresh_caller_commands(server, client_socket, name, player_data):
    """为 caller 重新下发当前位置的指令列表"""
    lobby = server.lobby_engine
    loc = lobby.get_player_location(name)
    cmds = lobby.get_commands_for_location(loc, player_data)
    server.send_to(client_socket, {'type': COMMANDS_UPDATE, 'commands': cmds})


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

    # 5. save / status — 仅在 result 显式请求时保存（减少不必要的磁盘 IO）
    if caller_name and caller_data and result.get('save'):
        _save_and_status(server, caller_socket, name=caller_name, player_data=caller_data)

    # 5b. refresh_status: 为所有涉及玩家重新下发状态（奖惩变动后）
    if result.get('refresh_status'):
        for target in result['refresh_status']:
            if target == caller_name:
                continue
            target_data = server._get_player_data(target)
            if target_data:
                _send_status_to_player(server, target, target_data)

    # 6. refresh_commands: 仅为 caller 重新下发指令列表
    if result.get('refresh_commands'):
        if caller_name and caller_socket:
            _refresh_caller_commands(server, caller_socket, caller_name, caller_data)

    # 7. refresh_room_list: 向所有大厅玩家广播最新房间列表
    if result.get('refresh_room_list'):
        _broadcast_room_list(server)


def _broadcast_room_list(server):
    """向所有在大厅的玩家广播最新房间列表"""
    from ..config import DEFAULT_LOCATION
    lobby = server.lobby_engine
    rooms = lobby.get_all_rooms()
    msg = {'type': ROOM_LIST, 'rooms': rooms}
    for name, loc in lobby.player_locations.items():
        if loc == DEFAULT_LOCATION:
            server.send_to_player(name, msg)


def handle_simple_result(server, client_socket, name, player_data, result):
    """处理不含 send_to_caller/send_to_players 的简单游戏结果"""
    action = result.get('action', '')

    if result.get('message'):
        server.send_to(client_socket, {'type': GAME, 'text': result['message']})
    for evt in result.get('game_events', []):
        server.send_to(client_socket, evt)
    if 'room_data' in result:
        server.send_to(client_socket, {'type': ROOM_UPDATE, 'room_data': result['room_data']})

    _send_location_change(server, client_socket, name, player_data, action, result)
    _save_and_status(server, client_socket, name, player_data)

    if result.get('refresh_commands'):
        _refresh_caller_commands(server, client_socket, name, player_data)


def dispatch_result(server, client_socket, name, player_data, result):
    """分发 lobby_engine.process_command 的结果"""
    if isinstance(result, dict):
        # ── send_to_caller / send_to_players 优先 ──
        if 'send_to_caller' in result or 'send_to_players' in result:
            dispatch_game_result(server, result, client_socket, name, player_data)
            return

        action = result.get('action')
        if action:
            handler = _ACTION_HANDLERS.get(action)
            if handler is not None:
                handler(server, client_socket, name, player_data, result)
            else:
                handle_simple_result(server, client_socket, name, player_data, result)
            return

    server.send_to(client_socket, {'type': GAME, 'text': result})
    PlayerManager.save_player_data(name, player_data)
    server.send_player_status(client_socket, player_data)

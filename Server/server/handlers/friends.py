"""好友系统消息处理器 — friend_request / friend_accept / friend_reject / friend_remove"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import logging

from . import register
from ..player.manager import PlayerManager
from ..msg_types import FRIEND_REQUEST, SYSTEM

logger = logging.getLogger(__name__)
_SOCIAL_FIELDS = ('friends', 'pending_friend_requests')


@contextmanager
def _friend_transaction(server, *names: str):
    """统一锁序：lobby 状态 → 玩家存档 → server 连接映射。"""
    with server.lobby_engine._lock:
        with PlayerManager.lock_players(*names):
            yield


def _merge_social_fields(target: dict, source: dict) -> None:
    for field in _SOCIAL_FIELDS:
        target[field] = deepcopy(source.get(field, []))


def _load_locked_players(server, names: tuple[str, ...]):
    """调用方已持有 lobby 和玩家锁；先读最新在线镜像。"""
    data_by_name = {}
    sockets = {}
    with server.lock:
        for player_name in names:
            client_socket = server._name_to_socket.get(player_name)
            info = server.clients.get(client_socket) if client_socket else None
            lobby_data = server.lobby_engine.online_players.get(player_name)
            if (
                info
                and info.get('state') == 'playing'
                and info.get('name') == player_name
                and (lobby_data or info.get('data'))
            ):
                data_by_name[player_name] = deepcopy(
                    lobby_data or info['data'])
                sockets[player_name] = client_socket

    for player_name in names:
        if player_name not in data_by_name:
            data = PlayerManager.load_player_data(player_name)
            if data:
                data_by_name[player_name] = data
    return data_by_name, sockets


def _save_locked_player(name: str, data: dict) -> None:
    PlayerManager.save_player_data(name, deepcopy(data))


def _save_locked_players(
        updates: dict[str, dict], originals: dict[str, dict]) -> None:
    """提交多玩家更新；写入失败时恢复已写玩家。"""
    saved = []
    try:
        for name in sorted(updates):
            _save_locked_player(name, updates[name])
            saved.append(name)
    except OSError:
        for name in reversed(saved):
            try:
                _save_locked_player(name, originals[name])
            except OSError:
                logger.exception("回滚好友事务失败: %s", name)
        raise


def _update_online_mirrors(server, updates: dict[str, dict]) -> dict[str, object]:
    """只合并好友字段，保留在线对象中的并发经济和名片变更。"""
    sockets = {}
    for name, data in updates.items():
        lobby_data = server.lobby_engine.online_players.get(name)
        if lobby_data is not None:
            _merge_social_fields(lobby_data, data)
    with server.lock:
        for name, data in updates.items():
            client_socket = server._name_to_socket.get(name)
            info = server.clients.get(client_socket) if client_socket else None
            if (
                info
                and info.get('state') == 'playing'
                and info.get('name') == name
                and info.get('data') is not None
            ):
                _merge_social_fields(info['data'], data)
                sockets[name] = client_socket
    return sockets


def _commit_social_updates(
        server, updates: dict[str, dict]) -> tuple[dict[str, dict], dict[str, object]]:
    """把好友字段合并到事务末尾的最新完整记录后再持久化。"""
    latest, _ = _load_locked_players(server, tuple(updates))
    committed = {}
    originals = {}
    for name, social_data in updates.items():
        current = latest.get(name)
        if current is None:
            continue
        originals[name] = deepcopy(current)
        merged = deepcopy(current)
        _merge_social_fields(merged, social_data)
        committed[name] = merged
    _save_locked_players(committed, originals)
    return committed, _update_online_mirrors(server, committed)


def send_friend_request(server, name: str, target: str, player_data: dict) -> str | None:
    """发送好友申请核心逻辑（共享给 result_dispatcher）。"""
    if not target or target == name:
        return '无效目标'

    with _friend_transaction(server, name, target):
        records, _ = _load_locked_players(server, (name, target))
        source_data = records.get(name)
        target_data = records.get(target)
        if not target_data:
            return f'用户 {target} 不存在。'
        if not source_data:
            return '加载玩家数据失败'
        if target in source_data.get('friends', []):
            return f'{target} 已经是你的好友'

        pending = target_data.setdefault('pending_friend_requests', [])
        if name in pending:
            return '已发送过好友申请，等待对方回应'
        pending.append(name)
        committed, online = _commit_social_updates(
            server, {target: target_data})
        target_data = committed[target]

    target_socket = online.get(target)
    if target_socket:
        server.send_to(target_socket, {
            'type': FRIEND_REQUEST,
            'from': name,
            'pending': list(target_data.get('pending_friend_requests', [])),
        })
    return None


@register('friend_request')
def handle_friend_request(server, client_socket, name, player_data, msg):
    target = msg.get('name', '').strip()
    if not target:
        server.send_to(client_socket, {'type': SYSTEM, 'text': '请指定用户名。'})
        return
    err = send_friend_request(server, name, target, player_data)
    if err:
        server.send_to(client_socket, {'type': SYSTEM, 'text': err})
    else:
        server.send_to(client_socket, {'type': SYSTEM, 'text': f'已向 {target} 发送好友申请'})


@register('friend_accept')
def handle_friend_accept(server, client_socket, name, player_data, msg):
    target = msg.get('name', '').strip()
    if not target or target == name:
        return

    changed = False
    target_data = None
    with _friend_transaction(server, name, target):
        records, _ = _load_locked_players(server, (name, target))
        own_data = records.get(name)
        target_data = records.get(target)
        if own_data and target_data:
            pending = own_data.get('pending_friend_requests', [])
            if target in pending:
                pending.remove(target)
                if target not in own_data.setdefault('friends', []):
                    own_data['friends'].append(target)
                if name not in target_data.setdefault('friends', []):
                    target_data['friends'].append(name)
                committed, online = _commit_social_updates(
                    server, {name: own_data, target: target_data})
                own_data = committed[name]
                target_data = committed[target]
                player_data = own_data
                changed = True
            else:
                online = {}
        else:
            own_data = player_data
            online = {}

    if changed:
        target_socket = online.get(target)
        if target_socket:
            server._send_friend_list(target_socket, target_data)
            server.send_to(target_socket, {
                'type': SYSTEM,
                'text': f'{name} 已接受你的好友申请',
            })
    server._send_friend_list(client_socket, player_data)
    server.send_to(client_socket, {
        'type': FRIEND_REQUEST,
        'pending': list(player_data.get('pending_friend_requests', [])),
    })


@register('friend_reject')
def handle_friend_reject(server, client_socket, name, player_data, msg):
    target = msg.get('name', '').strip()
    if not target:
        return

    with _friend_transaction(server, name):
        records, _ = _load_locked_players(server, (name,))
        own_data = records.get(name)
        if own_data:
            pending = own_data.get('pending_friend_requests', [])
            if target in pending:
                pending.remove(target)
                committed, _ = _commit_social_updates(
                    server, {name: own_data})
                own_data = committed[name]
                player_data = own_data

    server.send_to(client_socket, {'type': SYSTEM, 'text': f'已拒绝 {target} 的好友申请'})
    server.send_to(client_socket, {
        'type': FRIEND_REQUEST,
        'pending': list(player_data.get('pending_friend_requests', [])),
    })


@register('friend_remove')
def handle_friend_remove(server, client_socket, name, player_data, msg):
    target = msg.get('name', '').strip()
    if not target:
        server._send_friend_list(client_socket, player_data)
        return

    changed = False
    target_data = None
    with _friend_transaction(server, name, target):
        records, _ = _load_locked_players(server, (name, target))
        own_data = records.get(name)
        target_data = records.get(target)
        if own_data and target_data and target in own_data.get('friends', []):
            own_data['friends'].remove(target)
            if name in target_data.get('friends', []):
                target_data['friends'].remove(name)
            committed, online = _commit_social_updates(
                server, {name: own_data, target: target_data})
            own_data = committed[name]
            target_data = committed[target]
            player_data = own_data
            changed = True
        else:
            online = {}

    if changed:
        target_socket = online.get(target)
        if target_socket:
            server._send_friend_list(target_socket, target_data)
            server.send_to(target_socket, {
                'type': SYSTEM,
                'text': f'{name} 已将你从好友列表移除',
            })
    server._send_friend_list(client_socket, player_data)

"""回城系统 — 吟唱4秒传送至初始城镇出生点，冷却4分钟"""

from __future__ import annotations

import time

from ...config import DEFAULT_LOCATION, DEFAULT_MAP

_CHANNEL_TIME = 4.0
_COOLDOWN_TIME = 240.0  # 4 分钟

_recall_state: dict[str, dict] = {}
_recall_cooldown: dict[str, float] = {}


def is_recalling(player_name: str) -> bool:
    return player_name in _recall_state


def cancel_recall(player_name: str) -> bool:
    """取消回城，返回是否确实在回城中"""
    return _recall_state.pop(player_name, None) is not None


def cleanup_player(player_name: str) -> None:
    """玩家断线时清理所有回城数据，防止内存泄漏"""
    _recall_state.pop(player_name, None)
    _recall_cooldown.pop(player_name, None)


def cmd_recall(engine, lobby, player_name, player_data, args, map_id, map_data):
    """发起回城 — 需要站定吟唱"""
    from .fishing import is_fishing

    if is_fishing(player_name):
        return "你正在钓鱼，无法回城。"

    if is_recalling(player_name):
        return "你已经在回城了。"

    last = _recall_cooldown.get(player_name, 0.0)
    remaining = _COOLDOWN_TIME - (time.monotonic() - last)
    if remaining > 0:
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        return f"回城冷却中，还需 {mins}分{secs}秒。"

    pos = engine._positions.get(player_name, [0, 0])
    if map_id == DEFAULT_MAP:
        spawn = list(map_data.get('spawn', [20, 14]))
        if list(pos) == spawn:
            return "你已经在出生点了。"

    _recall_state[player_name] = {
        'start_time': time.monotonic(),
        'pos': list(pos),
        'map_id': map_id,
    }

    return {
        'action': 'recall_start',
        'send_to_caller': [{
            'type': 'game_event', 'game_type': 'world',
            'event': 'recall_start',
            'data': {'channel_time': _CHANNEL_TIME},
        }, {
            'type': 'game', 'text': '正在回城，请勿移动...',
        }],
        'refresh_commands': True,
    }


def cmd_recall_complete(engine, lobby, player_name, player_data,
                        args, map_id, map_data):
    """回城完成 — 客户端吟唱计时结束后触发"""
    from .town_map import load_map

    state = _recall_state.pop(player_name, None)
    if not state:
        return ""

    if map_id != state['map_id']:
        return ""

    cur_pos = list(engine._positions.get(player_name, [0, 0]))
    if cur_pos != state['pos']:
        return "回城被中断了。"

    _recall_cooldown[player_name] = time.monotonic()

    home_data = load_map(DEFAULT_MAP)
    spawn = list(home_data.get('spawn', [20, 14]))

    if map_id == DEFAULT_MAP:
        # 同地图：只移动到出生点
        old_pos = list(engine._positions[player_name])
        engine._positions[player_name] = spawn
        engine._save_world_state(player_name, player_data)
        send_to_players = engine._build_player_delta(
            player_name, old_pos, spawn, map_id)
    else:
        # 跨地图：切换到初始城镇
        notify = engine._switch_map(player_name, DEFAULT_MAP, spawn)
        lobby.set_player_location(player_name, DEFAULT_LOCATION)
        engine._save_world_state(player_name, player_data, DEFAULT_LOCATION)
        send_to_players = notify

    result = {
        'action': 'recall_complete',
        'send_to_caller': [
            engine._build_map_update(player_name),
            {'type': 'game', 'text': '回城成功！'},
        ],
        'save': True,
        'refresh_commands': True,
    }
    if send_to_players:
        result['send_to_players'] = send_to_players
    return result

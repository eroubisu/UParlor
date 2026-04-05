"""钓鱼系统 — /fish 和 /pull 指令

机制:
1. 站在水边1格 + 背包有钓竿 → /fish 可用
2. /fish → 进入钓鱼状态, 服务端记录 cast_time + bite_delay
3. 客户端本地计时, bite_delay 秒后提示"鱼上钩了！"
4. /pull → 服务端校验时间窗口 → 成功/失败
5. 移动自动取消钓鱼
"""

from __future__ import annotations

import json
import os
import random
import time

_dir = os.path.dirname(__file__)
_rewards_path = os.path.join(_dir, 'data', 'rewards.json')

_rewards: dict = {}


def _load_rewards() -> dict:
    global _rewards
    if not _rewards and os.path.exists(_rewards_path):
        with open(_rewards_path, 'r', encoding='utf-8') as f:
            _rewards = json.load(f)
    return _rewards.get('fishing', {})


# {player_name: {'cast_time': float, 'bite_delay': float, 'map_id': str}}
_fishing_state: dict[str, dict] = {}


def is_fishing(player_name: str) -> bool:
    return player_name in _fishing_state


def cancel_fishing(player_name: str):
    _fishing_state.pop(player_name, None)


def is_near_water_check(map_data: dict, pos: list[int]) -> bool:
    """检查位置附近是否有水（供 get_commands 用）"""
    from .town_map import is_near_water
    return is_near_water(map_data, pos[0], pos[1])


def has_fishing_rod(player_data: dict) -> bool:
    """检查背包或装备中是否有钓竿"""
    from ...systems.items import inv_total
    inv = player_data.get('inventory', {})
    if inv_total(inv, 'fishing_rod') > 0:
        return True
    equip = player_data.get('equipment', {})
    if (equip.get('main_hand') or {}).get('id') == 'fishing_rod':
        return True
    return False


def cmd_fish(engine, lobby, player_name, player_data, args, map_id, map_data):
    """甩出鱼线 — 需要在水边且有钓竿"""
    from .town_map import is_near_water

    if is_fishing(player_name):
        return "你已经在钓鱼了，等待鱼上钩或 /pull 收杆。"

    pos = engine._positions[player_name]
    if not is_near_water(map_data, pos[0], pos[1]):
        return "这里附近没有水，无法钓鱼。"

    if not has_fishing_rod(player_data):
        return "你没有钓竿。去渔具店买一根吧。"

    cfg = _load_rewards()
    lo, hi = cfg.get('bite_delay', [3.0, 8.0])
    bite_delay = random.uniform(lo, hi)

    _fishing_state[player_name] = {
        'cast_time': time.monotonic(),
        'bite_delay': bite_delay,
        'map_id': map_id,
    }

    return {
        'action': 'fish_cast',
        'send_to_caller': [{
            'type': 'game_event', 'game_type': 'world',
            'event': 'fish_cast',
            'data': {'bite_delay': round(bite_delay, 1)},
        }, {
            'type': 'game', 'text': '你甩出鱼线，静静等待...',
        }],
        'refresh_commands': True,
    }


def cmd_pull(engine, lobby, player_name, player_data, args, map_id, map_data):
    """收杆 — 在鱼上钩后的时间窗口内操作"""
    state = _fishing_state.pop(player_name, None)
    if not state:
        return "你没在钓鱼。"

    cfg = _load_rewards()
    pull_window = cfg.get('pull_window', 2.0)
    elapsed = time.monotonic() - state['cast_time']
    bite_time = state['bite_delay']

    if elapsed < bite_time:
        # 太早了
        return {
            'action': 'fish_result',
            'send_to_caller': [{
                'type': 'game_event', 'game_type': 'world',
                'event': 'fish_result',
                'data': {'success': False, 'msg': '收杆太早了，鱼还没上钩！'},
            }, {
                'type': 'game', 'text': '收杆太早了，鱼还没上钩！',
            }],
            'refresh_commands': True,
        }

    if elapsed > bite_time + pull_window:
        # 超时
        return {
            'action': 'fish_result',
            'send_to_caller': [{
                'type': 'game_event', 'game_type': 'world',
                'event': 'fish_result',
                'data': {'success': False, 'msg': '鱼跑了...下次要快点！'},
            }, {
                'type': 'game', 'text': '鱼跑了...下次要快点！',
            }],
            'refresh_commands': True,
        }

    # 成功！按权重抽取结果
    catches = cfg.get('catches', [])
    if not catches:
        return "这里没有鱼..."

    total_w = sum(c.get('weight', 1) for c in catches)
    roll = random.uniform(0, total_w)
    cumulative = 0
    catch = catches[-1]
    for c in catches:
        cumulative += c.get('weight', 1)
        if roll <= cumulative:
            catch = c
            break

    item_id = catch.get('id')
    exp = catch.get('exp', 0)
    gold = catch.get('gold', 0)

    if not item_id:
        # 空钩
        msg = catch.get('msg', '什么也没钓到...')
        result = {
            'action': 'fish_result',
            'send_to_caller': [{
                'type': 'game_event', 'game_type': 'world',
                'event': 'fish_result',
                'data': {'success': False, 'msg': msg},
            }, {
                'type': 'game', 'text': msg,
            }],
            'refresh_commands': True,
        }
    else:
        # 得到鱼
        from ...systems.items import inv_add, get_item_name
        from ...systems.leveling import check_level_up
        inventory = player_data.setdefault('inventory', {})
        inv_add(inventory, item_id, 0)
        if gold > 0:
            player_data['gold'] = player_data.get('gold', 0) + gold
        if exp > 0:
            player_data['exp'] = player_data.get('exp', 0) + exp
        leveled = check_level_up(player_data)
        item_name = get_item_name(item_id)
        parts = [f"钓到了 {item_name}！"]
        if exp > 0:
            parts.append(f"+{exp} 经验")
        if gold > 0:
            parts.append(f"+{gold} 金币")
        if leveled:
            parts.append(f"升级到 Lv.{leveled[-1]}！")
        msg = ' '.join(parts)

        result = {
            'action': 'fish_result',
            'send_to_caller': [{
                'type': 'game_event', 'game_type': 'world',
                'event': 'fish_result',
                'data': {'success': True, 'item': item_id, 'msg': msg},
            }, {
                'type': 'game', 'text': msg,
            }],
            'save': True,
            'refresh_commands': True,
        }

    return result

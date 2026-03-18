"""物品操作指令 — /use, /gift, /drop

handler 签名: (lobby, player_name, player_data, args, location) -> dict | str | None

物品键格式: "item_id:quality"（如 rename_card:2），不带品质默认 0。
品质影响效果: 数值类效果乘以品质倍率。
"""

from __future__ import annotations

from .items import (
    get_item_info, get_item_name,
    inv_get, inv_add, inv_sub, parse_item_key, quality_mult,
    get_game_use_handler,
)
from .effect_engine import process_effect
from ..player.manager import PlayerManager


# ══════════════════════════════════════════════════
#  物品使用调度
# ══════════════════════════════════════════════════

# handler 签名: (lobby, player_name, player_data, method_id, quality) -> result
_USE_HANDLERS: dict[str, callable] = {}


def register_use_handler(item_id: str, handler=None):
    """注册某物品的使用处理器。

    装饰器: @register_use_handler('rename_card')
    函数调用: register_use_handler('item_id', handler)
    """
    if handler is not None:
        _USE_HANDLERS[item_id] = handler
        return handler

    def decorator(fn):
        _USE_HANDLERS[item_id] = fn
        return fn
    return decorator


# ══════════════════════════════════════════════════
#  /use — 使用物品（格式: /use item_id:quality [method_id]）
# ══════════════════════════════════════════════════

def cmd_use(lobby, player_name, player_data, args, location):
    if not args:
        return "用法: /use <物品ID> [方式]"

    parts = args.split(None, 1)
    item_key = parts[0]
    method_id = parts[1].strip() if len(parts) > 1 else None

    item_id, quality = parse_item_key(item_key)
    inventory = player_data.get('inventory', {})
    if inv_get(inventory, item_id, quality) <= 0:
        return "你没有这个物品。"

    info = get_item_info(item_id)
    if not info:
        return "未知物品。"

    use_methods = info.get('use_methods', [])
    if not use_methods:
        return f"{info['name']} 无法使用。"

    # 单一用途：直接执行
    if len(use_methods) == 1:
        return _dispatch_use(lobby, player_name, player_data, item_id, quality, use_methods[0]['id'], location)

    # 多用途需指定 method
    if method_id is None:
        lines = ["请选择使用方式:"]
        for m in use_methods:
            lines.append(f"  /use {item_key} {m['id']} — {m['name']}")
        return "\n".join(lines)

    valid = {m['id'] for m in use_methods}
    if method_id not in valid:
        return "无效的使用方式。"

    return _dispatch_use(lobby, player_name, player_data, item_id, quality, method_id, location)


def _dispatch_use(lobby, player_name, player_data, item_id, quality, method_id, location=None):
    # 优先级 1: 游戏级 handler
    game_id = lobby._get_game_for_location(location) if location else None
    game_handler = get_game_use_handler(game_id, item_id)
    if game_handler:
        return game_handler(lobby, player_name, player_data, method_id, quality)

    # 优先级 2: 全局 handler
    handler = _USE_HANDLERS.get(item_id)
    if handler:
        return handler(lobby, player_name, player_data, method_id, quality)

    # 无专用 handler → method_id=='equip' 通用装备
    if method_id == 'equip':
        from .equipment import equip_item
        result = equip_item(player_data, item_id, quality)
        PlayerManager.save_player_data(player_name, player_data)
        return {'action': 'status_refresh', 'message': result}

    # 声明式效果引擎
    info = get_item_info(item_id)
    if info and info.get('effect'):
        result = process_effect(player_data, info['effect'], quality)
        if result:
            inventory = player_data.get('inventory', {})
            inv_sub(inventory, item_id, quality)
            return result

    return "此物品暂无使用效果。"


# ══════════════════════════════════════════════════
#  /gift — 赠送物品（格式: /gift item_id:quality）
# ══════════════════════════════════════════════════

def cmd_gift(lobby, player_name, player_data, args, location):
    if not args:
        return "用法: /gift <物品ID>"

    parts = args.split(None, 1)
    item_key = parts[0]
    item_id, quality = parse_item_key(item_key)

    inventory = player_data.get('inventory', {})
    if inv_get(inventory, item_id, quality) <= 0:
        return "你没有这个物品。"

    name = get_item_name(item_id)
    lobby.pending_confirms[player_name] = {
        'type': 'gift_item',
        'data': {'item_id': item_id, 'quality': quality, 'item_name': name},
    }
    return f"赠送 {name}，请输入对方名字:"


# ══════════════════════════════════════════════════
#  /drop — 丢弃物品（格式: /drop item_id:quality）
# ══════════════════════════════════════════════════

def cmd_drop(lobby, player_name, player_data, args, location):
    if not args:
        return "用法: /drop <物品ID>"

    parts = args.split(None, 2)
    item_key = parts[0]
    item_id, quality = parse_item_key(item_key)

    inventory = player_data.get('inventory', {})
    if inv_get(inventory, item_id, quality) <= 0:
        return "你没有这个物品。"

    name = get_item_name(item_id)

    # /drop key y [n] — 跳过确认直接丢弃
    if len(parts) > 1 and parts[1].strip().lower() == 'y':
        try:
            count = max(1, int(parts[2])) if len(parts) > 2 else 1
        except ValueError:
            count = 1
        have = inv_get(inventory, item_id, quality)
        count = min(count, have)
        for _ in range(count):
            inv_sub(inventory, item_id, quality)
        return f"已丢弃 {name} x{count}。"

    lobby.pending_confirms[player_name] = {
        'type': 'drop_item',
        'data': {'item_id': item_id, 'quality': quality, 'item_name': name},
    }
    return f"确认丢弃 {name} x1？输入 /y 确认，其他取消:"


# ══════════════════════════════════════════════════
#  内置物品使用处理
# ══════════════════════════════════════════════════

@register_use_handler('rename_card')
def _use_rename_card(lobby, player_name, player_data, method_id, quality=0):
    """改名卡 — 进入改名待确认流程（品质不影响效果）"""
    lobby.pending_confirms[player_name] = {
        'type': 'use_rename_card',
        'data': {'quality': quality},
    }
    return "请输入新名字:"


# exp_potion — 由声明式效果引擎自动处理 (effect.type=add_exp)


@register_use_handler('lucky_coin')
def _use_lucky_coin(lobby, player_name, player_data, method_id, quality=0):
    """幸运硬币 — flip: 抛硬币; wish: 许愿（品质倍率影响金币范围）"""
    import random
    inventory = player_data.get('inventory', {})
    if method_id == 'flip':
        result = random.choice(['正面', '反面'])
        return f"你抛出了幸运硬币... {result}！"
    elif method_id == 'wish':
        info = get_item_info('lucky_coin') or {}
        effect = info.get('effect', {})
        mult = quality_mult(quality)
        gold_min = int(effect.get('wish_gold_min', 10) * mult)
        gold_max = int(effect.get('wish_gold_max', 100) * mult)
        inv_sub(inventory, 'lucky_coin', quality)
        gold_bonus = random.randint(gold_min, gold_max)
        player_data['gold'] = player_data.get('gold', 0) + gold_bonus
        return f"你默默许了个愿... 硬币化为金光，获得 {gold_bonus} 金币！"
    return "无效操作。"


@register_use_handler('firework')
def _use_firework(lobby, player_name, player_data, method_id, quality=0):
    """烟花 — 消耗并在系统频道广播"""
    inventory = player_data.get('inventory', {})
    inv_sub(inventory, 'firework', quality)
    return {
        'action': 'firework',
        'send_to_caller': "你燃放了一朵烟花！",
        'broadcast': f"* {player_name} 燃放了一朵绚丽的烟花！",
        'save': True,
    }


@register_use_handler('gift_box')
def _use_gift_box(lobby, player_name, player_data, method_id, quality=0):
    """礼盒 — 品质倍率影响奖励数量"""
    import random
    inventory = player_data.get('inventory', {})
    inv_sub(inventory, 'gift_box', quality)
    info = get_item_info('gift_box') or {}
    rewards = info.get('effect', {}).get('rewards', [])
    if not rewards:
        return "打开礼盒... 空空如也。"
    reward = random.choice(rewards)
    reward_id = reward['id']
    reward_count = max(1, int(reward['count'] * quality_mult(quality)))
    reward_name = get_item_name(reward_id)
    if reward_id == 'gold':
        player_data['gold'] = player_data.get('gold', 0) + reward_count
    else:
        inv_add(inventory, reward_id, 0, reward_count)
    return f"打开礼盒... 获得了 {reward_name} x{reward_count}！"


# mystic_scroll — 由声明式效果引擎自动处理 (effect.type=add_exp)


@register_use_handler('teleport_stone')
def _use_teleport_stone(lobby, player_name, player_data, method_id, quality=0):
    """传送石 — 暂无已解锁的传送目的地"""
    return "传送石闪烁了一下... 但没有可用的传送目的地。"


@register_use_handler('enchanted_ring')
def _use_enchanted_ring(lobby, player_name, player_data, method_id, quality=0):
    """附魔戒指 — equip: 穿戴装备; disenchant: 分解为金币"""
    inventory = player_data.get('inventory', {})
    if method_id == 'equip':
        from .equipment import equip_item
        return equip_item(player_data, 'enchanted_ring', quality)
    elif method_id == 'disenchant':
        inv_sub(inventory, 'enchanted_ring', quality)
        gold_gain = int(30 * quality_mult(quality))
        player_data['gold'] = player_data.get('gold', 0) + gold_gain
        return f"你分解了附魔戒指，获得 {gold_gain} 金币。"
    return "无效操作。"


# ancient_tome — 由声明式效果引擎自动处理 (effect.type=add_exp)


# star_fragment — 由声明式效果引擎自动处理 (effect.type=add_exp)
# healing_herb — 由声明式效果引擎自动处理 (effect.type=heal_hp)


# ══════════════════════════════════════════════════
#  待确认处理器（由 confirmation 系统调用）
# ══════════════════════════════════════════════════

def pending_use_rename_card(lobby, player_name, player_data, cmd, raw_input, pending_data):
    """处理改名卡使用 — 输入新名字后设置标准 rename 确认"""
    from ..player.auth import validate_username
    new_name = raw_input.strip()
    err = validate_username(new_name)
    if err:
        return f"{err}已取消。"
    if PlayerManager.player_exists(new_name):
        return f"用户名 '{new_name}' 已被使用。"
    quality = pending_data.get('quality', 0) if isinstance(pending_data, dict) else 0
    lobby.pending_confirms[player_name] = {
        'type': 'rename',
        'data': {'new_name': new_name, 'rename_quality': quality},
    }
    return f"确定要改名为 '{new_name}' 吗？（消耗1张改名卡）\n输入 y 确认，其他取消。"


def pending_gift_item(lobby, player_name, player_data, cmd, raw_input, pending_data):
    """处理赠送物品 — 输入目标玩家名"""
    target_name = raw_input.strip()
    item_id = pending_data['item_id']
    item_name = pending_data['item_name']
    quality = pending_data.get('quality', 0)

    if target_name == player_name:
        return "不能赠送给自己。"
    if not PlayerManager.player_exists(target_name):
        return f"玩家 '{target_name}' 不存在。"

    inventory = player_data.get('inventory', {})
    if inv_get(inventory, item_id, quality) <= 0:
        return "你已经没有这个物品了。"

    # 扣除并赠送（保持品质）
    inv_sub(inventory, item_id, quality)
    target_data = PlayerManager.load_player_data(target_name)
    target_inv = target_data.setdefault('inventory', {})
    inv_add(target_inv, item_id, quality)
    PlayerManager.save_player_data(target_name, target_data)

    return {
        'action': 'gift_success',
        'message': f"已将 {item_name} x1 赠送给 {target_name}。",
        'target_name': target_name,
        'item_name': item_name,
        'save': True,
    }


def pending_drop_item(lobby, player_name, player_data, cmd, raw_input, pending_data):
    """处理丢弃物品 — 确认后移除"""
    if raw_input.strip().lower() != 'y':
        return "已取消丢弃。"

    item_id = pending_data['item_id']
    item_name = pending_data['item_name']
    quality = pending_data.get('quality', 0)
    inventory = player_data.get('inventory', {})

    if inv_get(inventory, item_id, quality) <= 0:
        return "你已经没有这个物品了。"

    inv_sub(inventory, item_id, quality)
    return f"已丢弃 {item_name} x1。"

"""物品操作指令 — /use, /gift, /drop

handler 签名: (lobby, player_name, player_data, args, location) -> dict | str | None
"""

from __future__ import annotations

from .items import get_item_info, get_item_name
from ..player.manager import PlayerManager


# ══════════════════════════════════════════════════
#  物品使用调度
# ══════════════════════════════════════════════════

# handler 签名: (lobby, player_name, player_data, method_id) -> result
_USE_HANDLERS: dict[str, callable] = {}


def register_use_handler(item_id: str, handler) -> None:
    """注册某物品的使用处理器"""
    _USE_HANDLERS[item_id] = handler


# ══════════════════════════════════════════════════
#  /use — 使用物品
# ══════════════════════════════════════════════════

def cmd_use(lobby, player_name, player_data, args, location):
    if not args:
        return "用法: /use <物品ID> [方式]"

    parts = args.split(None, 1)
    item_id = parts[0]
    method_id = parts[1].strip() if len(parts) > 1 else None

    inventory = player_data.get('inventory', {})
    if inventory.get(item_id, 0) <= 0:
        return "你没有这个物品。"

    info = get_item_info(item_id)
    if not info:
        return "未知物品。"

    use_methods = info.get('use_methods', [])
    if not use_methods:
        return f"{info['name']} 无法使用。"

    # 单一用途：直接执行
    if len(use_methods) == 1:
        return _dispatch_use(lobby, player_name, player_data, item_id, use_methods[0]['id'])

    # 多用途需指定 method
    if method_id is None:
        lines = [f"请选择使用方式:"]
        for m in use_methods:
            lines.append(f"  /use {item_id} {m['id']} — {m['name']}")
        return "\n".join(lines)

    valid = {m['id'] for m in use_methods}
    if method_id not in valid:
        return "无效的使用方式。"

    return _dispatch_use(lobby, player_name, player_data, item_id, method_id)


def _dispatch_use(lobby, player_name, player_data, item_id, method_id):
    handler = _USE_HANDLERS.get(item_id)
    if handler:
        return handler(lobby, player_name, player_data, method_id)
    return "此物品暂无使用效果。"


# ══════════════════════════════════════════════════
#  /gift — 赠送物品
# ══════════════════════════════════════════════════

def cmd_gift(lobby, player_name, player_data, args, location):
    if not args:
        return "用法: /gift <物品ID>"

    parts = args.split(None, 1)
    item_id = parts[0]

    inventory = player_data.get('inventory', {})
    if inventory.get(item_id, 0) <= 0:
        return "你没有这个物品。"

    name = get_item_name(item_id)
    lobby.pending_confirms[player_name] = {
        'type': 'gift_item',
        'data': {'item_id': item_id, 'item_name': name},
    }
    return f"赠送 {name}，请输入对方名字:"


# ══════════════════════════════════════════════════
#  /drop — 丢弃物品
# ══════════════════════════════════════════════════

def cmd_drop(lobby, player_name, player_data, args, location):
    if not args:
        return "用法: /drop <物品ID>"

    parts = args.split(None, 1)
    item_id = parts[0]

    inventory = player_data.get('inventory', {})
    if inventory.get(item_id, 0) <= 0:
        return "你没有这个物品。"

    name = get_item_name(item_id)
    lobby.pending_confirms[player_name] = {
        'type': 'drop_item',
        'data': {'item_id': item_id, 'item_name': name},
    }
    return f"确认丢弃 {name} x1？输入 /y 确认，其他取消:"


# ══════════════════════════════════════════════════
#  内置物品使用处理
# ══════════════════════════════════════════════════

def _use_rename_card(lobby, player_name, player_data, method_id):
    """改名卡 — 进入改名待确认流程"""
    lobby.pending_confirms[player_name] = {'type': 'use_rename_card'}
    return "请输入新名字:"


register_use_handler('rename_card', _use_rename_card)


def _use_exp_potion(lobby, player_name, player_data, method_id):
    """经验药水 — 从 items.json effect.value 读取经验值"""
    from .leveling import check_level_up
    info = get_item_info('exp_potion') or {}
    value = info.get('effect', {}).get('value', 50)
    inventory = player_data.get('inventory', {})
    inventory['exp_potion'] = inventory.get('exp_potion', 0) - 1
    player_data['exp'] = player_data.get('exp', 0) + value
    msg = f"饮下经验药水，获得 {value} 点经验值！"
    leveled = check_level_up(player_data)
    if leveled:
        msg += f"\n升级了！当前等级: {leveled[-1]}"
    return msg


register_use_handler('exp_potion', _use_exp_potion)


def _use_lucky_coin(lobby, player_name, player_data, method_id):
    """幸运硬币 — flip: 抛硬币; wish: 许愿"""
    import random
    inventory = player_data.get('inventory', {})
    if method_id == 'flip':
        result = random.choice(['正面', '反面'])
        return f"你抛出了幸运硬币... {result}！"
    elif method_id == 'wish':
        info = get_item_info('lucky_coin') or {}
        effect = info.get('effect', {})
        gold_min = effect.get('wish_gold_min', 10)
        gold_max = effect.get('wish_gold_max', 100)
        inventory['lucky_coin'] = inventory.get('lucky_coin', 0) - 1
        gold_bonus = random.randint(gold_min, gold_max)
        player_data['gold'] = player_data.get('gold', 0) + gold_bonus
        return f"你默默许了个愿... 硬币化为金光，获得 {gold_bonus} 金币！"
    return "无效操作。"


register_use_handler('lucky_coin', _use_lucky_coin)


def _use_firework(lobby, player_name, player_data, method_id):
    """烟花 — 消耗并在系统频道广播"""
    inventory = player_data.get('inventory', {})
    inventory['firework'] = inventory.get('firework', 0) - 1
    return {
        'action': 'firework',
        'send_to_caller': f"你燃放了一朵烟花！",
        'broadcast': f"* {player_name} 燃放了一朵绚丽的烟花！",
        'save': True,
    }


register_use_handler('firework', _use_firework)


def _use_gift_box(lobby, player_name, player_data, method_id):
    """礼盒 — 从 items.json effect.rewards 读取奖池"""
    import random
    inventory = player_data.get('inventory', {})
    inventory['gift_box'] = inventory.get('gift_box', 0) - 1
    info = get_item_info('gift_box') or {}
    rewards = info.get('effect', {}).get('rewards', [])
    if not rewards:
        return "打开礼盒... 空空如也。"
    reward = random.choice(rewards)
    reward_id = reward['id']
    reward_count = reward['count']
    reward_name = get_item_name(reward_id)
    if reward_id == 'gold':
        player_data['gold'] = player_data.get('gold', 0) + reward_count
    else:
        inventory[reward_id] = inventory.get(reward_id, 0) + reward_count
    return f"打开礼盒... 获得了 {reward_name} x{reward_count}！"


register_use_handler('gift_box', _use_gift_box)


# ══════════════════════════════════════════════════
#  待确认处理器（由 confirmation 系统调用）
# ══════════════════════════════════════════════════

def pending_use_rename_card(lobby, player_name, player_data, cmd, raw_input, pending_data):
    """处理改名卡使用 — 输入新名字后设置标准 rename 确认"""
    new_name = raw_input.strip()
    if len(new_name) < 2 or len(new_name) > 12:
        return "用户名长度需要在2-12个字符之间。已取消。"
    if PlayerManager.player_exists(new_name):
        return f"用户名 '{new_name}' 已被使用。"
    lobby.pending_confirms[player_name] = {
        'type': 'rename',
        'data': new_name,
    }
    return f"确定要改名为 '{new_name}' 吗？（消耗1张改名卡）\n输入 y 确认，其他取消。"


def pending_gift_item(lobby, player_name, player_data, cmd, raw_input, pending_data):
    """处理赠送物品 — 输入目标玩家名"""
    target_name = raw_input.strip()
    item_id = pending_data['item_id']
    item_name = pending_data['item_name']

    if target_name == player_name:
        return "不能赠送给自己。"
    if not PlayerManager.player_exists(target_name):
        return f"玩家 '{target_name}' 不存在。"

    inventory = player_data.get('inventory', {})
    if inventory.get(item_id, 0) <= 0:
        return "你已经没有这个物品了。"

    # 扣除并赠送
    inventory[item_id] = inventory.get(item_id, 0) - 1
    target_data = PlayerManager.load_player_data(target_name)
    target_inv = target_data.setdefault('inventory', {})
    target_inv[item_id] = target_inv.get(item_id, 0) + 1
    PlayerManager.save_player_data(target_name, target_data)

    return f"已将 {item_name} x1 赠送给 {target_name}。"


def pending_drop_item(lobby, player_name, player_data, cmd, raw_input, pending_data):
    """处理丢弃物品 — 确认后移除"""
    if raw_input.strip().lower() != 'y':
        return "已取消丢弃。"

    item_id = pending_data['item_id']
    item_name = pending_data['item_name']
    inventory = player_data.get('inventory', {})

    if inventory.get(item_id, 0) <= 0:
        return "你已经没有这个物品了。"

    inventory[item_id] = inventory.get(item_id, 0) - 1
    return f"已丢弃 {item_name} x1。"


# ════════════════════════════════════════════════
#  自注册全局指令
# ════════════════════════════════════════════════

from ..lobby.command_registry import register_global


def _handle_use(lobby, player_name, player_data, args, location):
    return cmd_use(lobby, player_name, player_data, args, location)


def _handle_gift(lobby, player_name, player_data, args, location):
    return cmd_gift(lobby, player_name, player_data, args, location)


def _handle_drop(lobby, player_name, player_data, args, location):
    return cmd_drop(lobby, player_name, player_data, args, location)


register_global('use', _handle_use)
register_global('gift', _handle_gift)
register_global('drop', _handle_drop)

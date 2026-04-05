"""建筑指令处理器 — 商店买卖、锻造、酒馆休息

各建筑子位置的指令处理。WorldEngine.handle_command 根据当前位置委托到此。
"""

from __future__ import annotations

import json
import os
import random

from ...systems.items import (
    get_item_info, get_item_name,
    inv_get, inv_add, inv_sub, inv_total, parse_item_key,
)
from ...systems.recipes import get_recipes
from ...systems.attributes import heal_hp, heal_mp
from ...player.manager import PlayerManager

_dir = os.path.dirname(__file__)
_data_dir = os.path.join(_dir, 'data')


def _load_shops() -> dict:
    path = os.path.join(_data_dir, 'shops.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


_SHOPS = _load_shops()


def _get_recipes() -> dict:
    """从全局配方注册表获取 world 配方（由 games/__init__.py 注册）"""
    return get_recipes('world')


# ── 商店 — /buy, /sell ──

from ...core.protocol import build_select_menu as _menu_event


def cmd_buy(lobby, player_name, player_data, args, location):
    shop = _SHOPS.get(location)
    if not shop:
        return "这里没有商店。"
    buy_list = shop.get('buy', [])
    if not args:
        items = []
        for entry in buy_list:
            info = get_item_info(entry['id'])
            name = info.get('name', entry['id']) if info else entry['id']
            items.append({'label': name, 'desc': f"{entry['price']}G", 'command': f"/buy {entry['id']}"})
        return _menu_event('可购买的商品', items, '商店里空空如也。')

    parts = args.strip().split()
    item_id = parts[0]
    confirmed = len(parts) > 1 and parts[1] == 'y'
    entry = next((e for e in buy_list if e['id'] == item_id), None)
    if not entry:
        return "商店没有这个商品。"

    price = entry['price']
    gold = player_data.get('gold', 0)
    if gold < price:
        return f"金币不足（需要 {price}G，当前 {gold}G）。"

    info = get_item_info(item_id)
    name = info.get('name', item_id) if info else item_id

    if not confirmed:
        return _menu_event(f'确认购买 {name}（{price}G）？', [
            {'label': '确认购买', 'command': f'/buy {item_id} y'},
            {'label': '取消', 'command': ''},
        ])

    player_data['gold'] = gold - price
    inventory = player_data.setdefault('inventory', {})
    inv_add(inventory, item_id, 0)
    PlayerManager.save_player_data(player_name, player_data)
    return {
        'action': 'status_refresh',
        'send_to_caller': [{'type': 'game', 'text': f"购买了 {name}（-{price}G）。"}],
    }


def cmd_sell(lobby, player_name, player_data, args, location):
    shop = _SHOPS.get(location)
    if not shop:
        return "这里没有商店。"
    sell_rate = shop.get('sell_rate', 0.4)
    if not args:
        inventory = player_data.get('inventory', {})
        items = []
        for item_id, val in inventory.items():
            total = inv_total(inventory, item_id)
            if total <= 0:
                continue
            # 查找卖价
            base_price = 0
            for shop_data in _SHOPS.values():
                for entry in shop_data.get('buy', []):
                    if entry['id'] == item_id:
                        base_price = entry['price']
                        break
                if base_price:
                    break
            if not base_price:
                base_price = 10
            sell_price = max(1, int(base_price * sell_rate))
            name = get_item_name(item_id)
            items.append({'label': name, 'desc': f'x{total} · {sell_price}G', 'command': f'/sell {item_id}'})
        return _menu_event('出售物品', items, '你没有可出售的物品。')

    parts = args.strip().split()
    item_key = parts[0]
    confirmed = len(parts) > 1 and parts[1] == 'y'
    item_id, quality = parse_item_key(item_key)
    inventory = player_data.get('inventory', {})
    if inv_get(inventory, item_id, quality) <= 0:
        return "你没有这个物品。"

    # 查找原价(在所有商店的 buy 列表中)
    base_price = 0
    for shop_data in _SHOPS.values():
        for entry in shop_data.get('buy', []):
            if entry['id'] == item_id:
                base_price = entry['price']
                break
        if base_price:
            break
    if not base_price:
        base_price = 10  # 非商品的默认回收价

    sell_price = max(1, int(base_price * sell_rate))
    name = get_item_name(item_id)

    if not confirmed:
        return _menu_event(f'确认出售 {name}（+{sell_price}G）？', [
            {'label': '确认出售', 'command': f'/sell {item_key} y'},
            {'label': '取消', 'command': ''},
        ])

    inv_sub(inventory, item_id, quality)
    player_data['gold'] = player_data.get('gold', 0) + sell_price
    PlayerManager.save_player_data(player_name, player_data)
    return {
        'action': 'status_refresh',
        'send_to_caller': [{'type': 'game', 'text': f"卖出了 {name}（+{sell_price}G）。"}],
    }


# ── 锻造 — /forge ──

def cmd_forge(lobby, player_name, player_data, args, location):
    if location != 'building_blacksmith':
        return "只有在铁匠铺才能锻造。"
    if not args:
        items = []
        for recipe_id, recipe in _get_recipes().items():
            inputs_desc = ", ".join(
                f"{get_item_name(i['id'])}x{i['count']}" for i in recipe['inputs']
            )
            gold = recipe.get('gold_cost', 0)
            items.append({'label': recipe['name'], 'desc': f'{inputs_desc} + {gold}G', 'command': f'/forge {recipe_id}'})
        return _menu_event('锻造装备', items, '没有可用的配方。')

    parts = args.strip().split()
    recipe_id = parts[0]
    confirmed = len(parts) > 1 and parts[1] == 'y'
    recipe = _get_recipes().get(recipe_id)
    if not recipe:
        return "没有这个配方。"

    inventory = player_data.get('inventory', {})
    gold = player_data.get('gold', 0)
    gold_cost = recipe.get('gold_cost', 0)

    # 检查材料
    for inp in recipe['inputs']:
        if inv_total(inventory, inp['id']) < inp['count']:
            name = get_item_name(inp['id'])
            return f"材料不足: 需要 {name}x{inp['count']}。"
    if gold < gold_cost:
        return f"金币不足（需要 {gold_cost}G）。"

    if not confirmed:
        inputs_desc = ", ".join(
            f"{get_item_name(i['id'])}x{i['count']}" for i in recipe['inputs']
        )
        cost_desc = inputs_desc + (f" + {gold_cost}G" if gold_cost else "")
        return _menu_event(f'确认锻造 {recipe["name"]}（{cost_desc}）？', [
            {'label': '确认锻造', 'command': f'/forge {recipe_id} y'},
            {'label': '取消', 'command': ''},
        ])

    # 扣除材料和金币
    for inp in recipe['inputs']:
        inv_sub(inventory, inp['id'], 0, inp['count'])
    player_data['gold'] = gold - gold_cost

    # 产出
    msgs = []
    for out in recipe['outputs']:
        inv_add(inventory, out['id'], out.get('quality', 0), out.get('count', 1))
        name = get_item_name(out['id'])
        msgs.append(f"获得 {name}x{out.get('count', 1)}")

    PlayerManager.save_player_data(player_name, player_data)
    return {
        'action': 'status_refresh',
        'send_to_caller': [{'type': 'game', 'text': f"锻造成功！{'，'.join(msgs)}。"}],
    }


# ── 炼药 — /brew ──

def cmd_brew(lobby, player_name, player_data, args, location):
    if location != 'building_herbshop':
        return "只有在药草店才能炼药。"
    if not args:
        items = [
            {'label': '经验药水', 'desc': '治疗草药x2', 'command': '/brew exp_potion'},
        ]
        return _menu_event('炼药', items)

    parts = args.strip().split()
    brew_id = parts[0]
    confirmed = len(parts) > 1 and parts[1] == 'y'
    inventory = player_data.get('inventory', {})
    if brew_id == 'exp_potion':
        if inv_total(inventory, 'healing_herb') < 2:
            return "材料不足: 需要治疗草药x2。"
        if not confirmed:
            return _menu_event('确认炼药 经验药水（治疗草药x2）？', [
                {'label': '确认炼药', 'command': '/brew exp_potion y'},
                {'label': '取消', 'command': ''},
            ])
        inv_sub(inventory, 'healing_herb', 0, 2)
        inv_add(inventory, 'exp_potion', 0, 1)
        PlayerManager.save_player_data(player_name, player_data)
        return {
            'action': 'status_refresh',
            'send_to_caller': [{'type': 'game', 'text': '炼药成功！获得 经验药水x1。'}],
        }
    return "未知配方。"


# ── 酒馆 — /rest, /rumor ──

_RUMORS = [
    "听说北方的山脉深处有远古巨龙的宝藏...",
    "铁匠说最近有神秘商人出没，卖着稀有材料。",
    "冒险者公会贴出了讨伐哥布林的悬赏。",
    "有人在水边看到了发光的鱼，据说是好兆头。",
    "最近镇上来了一位游吟诗人，唱着很古老的歌。",
    "酒保悄悄告诉你，凤凰羽毛可以换到好东西。",
    "据说幸运硬币许愿时，品质越高运气越好。",
]


def cmd_rest(lobby, player_name, player_data, args, location):
    if location != 'building_tavern':
        return "只有在酒馆才能休息。"
    cost = 20
    gold = player_data.get('gold', 0)
    if gold < cost:
        return f"金币不足（休息需要 {cost}G，当前 {gold}G）。"

    if not args or args.strip() != 'y':
        return _menu_event(f'确认休息（{cost}G）？', [
            {'label': '确认休息', 'command': '/rest y'},
            {'label': '取消', 'command': ''},
        ])

    player_data['gold'] = gold - cost
    hp_healed = heal_hp(player_data, 9999)
    mp_healed = heal_mp(player_data, 9999)
    PlayerManager.save_player_data(player_name, player_data)
    return {
        'action': 'status_refresh',
        'send_to_caller': [{'type': 'game', 'text': f"休息完毕（-{cost}G）。HP 恢复 {hp_healed}，MP 恢复 {mp_healed}。"}],
    }


def cmd_rumor(lobby, player_name, player_data, args, location):
    if location != 'building_tavern':
        return "只有在酒馆才能打听消息。"
    return random.choice(_RUMORS)


# ── 公会 — /quest, /board ──

def cmd_quest(lobby, player_name, player_data, args, location):
    if location != 'building_guild':
        return "只有在冒险者公会才能接任务。"
    return "暂时没有可接取的任务。(开发中)"


def cmd_board(lobby, player_name, player_data, args, location):
    if location != 'building_guild':
        return "只有在冒险者公会才能查看布告栏。"
    return "布告栏上空空如也。(开发中)"


# ── 棋馆 — /play ──

# 建筑 → 可玩游戏映射（从 JSON 加载）
def _load_building_games():
    path = os.path.join(_data_dir, 'building_games.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

_BUILDING_GAMES = _load_building_games()


def cmd_play(lobby, player_name, player_data, args, location):
    available = _BUILDING_GAMES.get(location)
    if not available:
        return "这里没有可以玩的游戏。"

    if not args:
        from ...games import get_game
        items = []
        for gid in available:
            module = get_game(gid)
            if module:
                info = getattr(module, 'GAME_INFO', {})
                name = info.get('name', gid)
                items.append({'label': gid, 'desc': name, 'command': f'/play {gid}'})
        return _menu_event('选择游戏', items, '暂无可用游戏。')

    game_id = args.strip().split()[0]
    if game_id not in available:
        return "这里没有这个游戏。"

    return lobby._enter_game(player_name, player_data, game_id)


# ── 路由表 ──

BUILDING_HANDLERS = {
    'buy':    cmd_buy,
    'sell':   cmd_sell,
    'forge':  cmd_forge,
    'brew':   cmd_brew,
    'rest':   cmd_rest,
    'rumor':  cmd_rumor,
    'quest':  cmd_quest,
    'board':  cmd_board,
    'play':   cmd_play,
}

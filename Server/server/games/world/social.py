"""社交与交互指令 — enter, talk, user, addfriend + 跟随机制

独立函数 + SOCIAL_HANDLERS 路由表，与 building_handlers.py 模式一致。
每个函数签名: cmd_X(engine, lobby, player_name, player_data, args, map_id, map_data)
"""

from __future__ import annotations

from .town_map import (
    get_door, get_nearby_targets, get_nearby_interactables, is_walkable,
    load_map, get_all_teleport_destinations, teleport_cost,
)
from .building_handlers import _menu_event
from ...config import DEFAULT_LOCATION, OUTDOOR_MAP_TYPES


def _derive_location(meta: dict) -> str:
    """从目标地图 meta 推导 location 字符串"""
    map_type = meta.get('map_type', 'building')
    if map_type in OUTDOOR_MAP_TYPES:
        return DEFAULT_LOCATION
    return f"{map_type}_{meta.get('venue_type', meta.get('id', 'unknown'))}"


def _check_on_door(map_data: dict, pos: list[int]) -> bool:
    """玩家是否站在门上"""
    return get_door(map_data, pos[0], pos[1]) is not None


def _find_return_door(target_map: dict, source_map_id: str) -> list[int]:
    """在目标地图中找到通往 source_map_id 的门位置，找不到则用 spawn"""
    for bld_id, bld in target_map.get('buildings', {}).items():
        if bld_id == source_map_id:
            doors = bld.get('doors', [])
            if doors:
                return list(doors[0])
    return list(target_map.get('spawn', [4, 4]))


def cmd_enter(engine, lobby, player_name, player_data, args, map_id, map_data):
    """进入/离开建筑 — 站在门上时切换地图"""
    pos = engine._positions[player_name]
    door = get_door(map_data, pos[0], pos[1])
    if not door:
        return "这里没有可通过的门。"
    building_id = door.get('building_id', '')
    if not building_id:
        return "这扇门暂时无法通过。"

    # 加载目标地图，在其中找到指回当前地图的门作为落点
    target_map = load_map(building_id)
    if not target_map:
        return f"{door['name']} 暂时无法进入。"
    meta = target_map.get('meta', {})
    map_type = meta.get('map_type', 'building')
    location = _derive_location(meta)
    enter_pos = _find_return_door(target_map, map_id)

    # 保存当前位置（用于 handle_back 回城）
    world = player_data.setdefault('world', {})
    world['town_pos'] = list(pos)
    world['town_map'] = map_id

    notify = engine._switch_map(player_name, building_id, enter_pos)
    lobby.set_player_location(player_name, location)
    engine._save_world_state(player_name, player_data, location)

    # 跟随者也切换到同一建筑
    for fname in engine._get_followers_recursive(player_name):
        fdata = lobby.online_players.get(fname)
        if fdata and engine._maps.get(fname) == map_id:
            fn = engine._switch_map(fname, building_id, enter_pos)
            lobby.set_player_location(fname, location)
            engine._save_world_state(fname, fdata, location)
            for t, msgs in fn.items():
                notify.setdefault(t, []).extend(msgs)
            # 跟随者自身也需要收到完整地图更新
            f_map_update = engine._build_map_update(fname)
            notify.setdefault(fname, []).append(f_map_update)
            notify.setdefault(fname, []).append(
                {'type': 'game', 'text': f'跟随进入了 {door["name"]}。'})

    door_name = door['name']
    enter_text = f"前往 {door_name}。" if map_type in ('world', 'road') else f"进入了 {door_name}。"
    map_update = engine._build_map_update(player_name)
    map_update.setdefault('room_data', {})['ai_description'] = f"玩家进入了{door_name}"
    result = {
        'action': 'location_update',
        'send_to_caller': [
            map_update,
            {'type': 'game', 'text': enter_text},
        ],
        'location': location,
        'save': True,
    }
    if notify:
        result['send_to_players'] = notify
    return result


def cmd_talk(engine, lobby, player_name, player_data, args, map_id, map_data):
    """与NPC/玩家交谈"""
    pos = engine._positions[player_name]

    if args:
        target_name = args.strip()
        targets = get_nearby_targets(map_data, pos[0], pos[1], radius=2)
        target = None
        for t in targets:
            if t['name'] == target_name:
                target = t
                break
        if target:
            npc = map_data.get('_npc_map', {}).get(tuple(target['pos']))
            if npc:
                dialog = npc.get('dialog', '')
                return f"\\[{npc['name']}]: {dialog}" if dialog else f"{npc['name']} 沉默不语。"
            return f"{target['name']} 沉默不语。"
        # 检查是否为附近玩家
        for name in engine._map_players.get(map_id, ()):
            if name != player_name and name == target_name:
                p = engine._positions.get(name)
                if p and abs(p[0] - pos[0]) <= 2 and abs(p[1] - pos[1]) <= 2:
                    friends = player_data.get('friends', [])
                    if name in friends:
                        return {
                            'action': 'dm_player',
                            'send_to_caller': [{
                                'type': 'game_event',
                                'game_type': 'world',
                                'event': 'dm_player',
                                'data': {'target': name},
                            }],
                        }
                    return f"{name} 不是你的好友，无法私聊。"
        return f"附近没有名为 {target_name} 的人。"

    # /talk 无参 — 列出附近交谈对象
    targets = get_nearby_targets(map_data, pos[0], pos[1], radius=2)
    items = [{'label': f'◆ {t["name"]}', 'command': f"/talk {t['name']}"} for t in targets]
    for name in engine._map_players.get(map_id, ()):
        if name != player_name:
            p = engine._positions.get(name)
            if p and abs(p[0] - pos[0]) <= 2 and abs(p[1] - pos[1]) <= 2:
                items.append({'label': f'@ {name}', 'command': f"/talk {name}"})
    return _menu_event('与谁交谈？', items, '附近没有可以交谈的人。' if not items else '')


def cmd_map(engine, lobby, player_name, player_data, args, map_id, map_data):
    """刷新当前地图"""
    return {
        'action': 'world_map',
        'send_to_caller': [engine._build_map_update(player_name)],
    }


def cmd_user(engine, lobby, player_name, player_data, args, map_id, map_data):
    """查看附近玩家"""
    if args:
        target_name = args.strip()
        nearby = engine._get_nearby_players(player_name, radius=2)
        if target_name not in nearby:
            return f"附近没有名为 {target_name} 的玩家。"
        friends = player_data.get('friends', [])
        items = [
            {'label': f'跟随 {target_name}', 'command': f'/_follow_player {target_name}'},
        ]
        if target_name not in friends:
            items.append({'label': '添加好友', 'command': f'/addfriend {target_name}'})
        return _menu_event(target_name, items)
    # /user 无参
    nearby = engine._get_nearby_players(player_name, radius=2)
    items = [{'label': f'@ {n}', 'command': f'/user {n}'} for n in nearby]
    return _menu_event('附近玩家', items, '附近没有其他玩家。' if not items else '')


def cmd_addfriend(engine, lobby, player_name, player_data, args, map_id, map_data):
    """添加好友"""
    if not args:
        # 列出附近可添加的玩家
        friends = player_data.get('friends', [])
        nearby = engine._get_nearby_players(player_name, radius=2)
        items = [{'label': f'@ {n}', 'command': f'/addfriend {n}'}
                 for n in nearby if n not in friends]
        return _menu_event('添加谁为好友？', items, '附近没有可添加的玩家。')
    target_name = args.strip()
    if target_name == player_name:
        return "不能添加自己为好友。"
    friends = player_data.get('friends', [])
    if target_name in friends:
        return f"{target_name} 已经是你的好友了。"
    return {
        'action': 'friend_request',
        'target': target_name,
        'message': f'已向 {target_name} 发送好友申请。',
    }


def cmd_follow_player(engine, lobby, player_name, player_data, args, map_id, map_data):
    """通过 user 面板触发跟随（非指令）"""
    if not args:
        return ""
    target_name = args.strip()
    if target_name == player_name:
        return "不能跟随自己。"
    nearby = engine._get_nearby_players(player_name, radius=2)
    if target_name not in nearby:
        return f"附近没有名为 {target_name} 的玩家。"
    # 防止循环跟随
    check = target_name
    while check in engine._following:
        check = engine._following[check]
        if check == player_name:
            return "不能形成循环跟随。"
    engine._follow(player_name, target_name)
    # 跟随者瞬移到目标身后
    target_pos = engine._positions.get(target_name)
    if target_pos:
        facing = engine._facings.get(target_name, (0, 1))
        behind = [target_pos[0] - facing[0], target_pos[1] - facing[1]]
        if not is_walkable(map_data, behind[0], behind[1]):
            behind = list(target_pos)
        old_pos = list(engine._positions[player_name])
        engine._positions[player_name] = behind
        send_to_players = engine._build_player_delta(
            player_name, old_pos, behind, map_id)
        return {
            'action': 'follow_started',
            'send_to_caller': [
                engine._build_map_update(player_name),
                {'type': 'game', 'text': f"开始跟随 {target_name}。移动可取消跟随。"},
                {'type': 'game_event', 'game_type': 'world',
                 'event': 'follow_started', 'data': {'target': target_name}},
            ],
            'send_to_players': send_to_players,
            'save': True,
        }
    return f"开始跟随 {target_name}。"


def cmd_cancel_follow(engine, lobby, player_name, player_data, args, map_id, map_data):
    """取消跟随（任意移动键或客户端发送 cancel_follow）"""
    leader = engine._following.get(player_name)
    if not leader:
        return ""
    engine._unfollow(player_name)
    return {
        'action': 'follow_cancelled',
        'send_to_caller': [
            {'type': 'game', 'text': f"停止跟随 {leader}。"},
            {'type': 'game_event', 'game_type': 'world',
             'event': 'follow_cancelled', 'data': {}},
        ],
    }


def cmd_interact(engine, lobby, player_name, player_data, args, map_id, map_data):
    """交互 — 扫描 4 格内告示牌/传送阵/NPC，弹出选择菜单"""
    pos = engine._positions[player_name]

    if args:
        # 子菜单选中后回调: /_interact <type>:<index>
        return _do_interact(engine, lobby, player_name, player_data,
                            args.strip(), map_id, map_data)

    targets = get_nearby_interactables(map_data, pos[0], pos[1], radius=2)
    items = []
    type_counters: dict[str, int] = {}
    for t in targets:
        idx = type_counters.get(t['type'], 0)
        type_counters[t['type']] = idx + 1
        item: dict = {
            'label': t['name'],
            'command': f"/interact {t['type']}:{idx}",
        }
        if t.get('desc'):
            item['desc'] = t['desc']
        items.append(item)
    return _menu_event('交互', items, '附近没有可交互的东西。' if not items else '')


def _do_interact(engine, lobby, player_name, player_data,
                 target_key, map_id, map_data):
    """执行具体交互 — 直接查表，不重复扫描"""
    parts = target_key.split(':', 1)
    if len(parts) != 2:
        return "无效的交互目标。"
    t_type, t_idx_s = parts
    try:
        t_idx = int(t_idx_s)
    except ValueError:
        return "无效的交互目标。"

    pos = engine._positions[player_name]

    if t_type == 'sign':
        signs = [
            (sx, sy, text)
            for (sx, sy), text in map_data.get('_sign_map', {}).items()
            if text and abs(sx - pos[0]) <= 2 and abs(sy - pos[1]) <= 2
        ]
        if t_idx < 0 or t_idx >= len(signs):
            return "交互目标不存在。"
        return f"\\[告示牌] {signs[t_idx][2]}"

    if t_type == 'teleport':
        tps = [
            (tx, ty)
            for (tx, ty) in map_data.get('_teleport_map', {})
            if abs(tx - pos[0]) <= 2 and abs(ty - pos[1]) <= 2
        ]
        if t_idx < 0 or t_idx >= len(tps):
            return "交互目标不存在。"
        return _interact_teleport(engine, lobby, player_name, player_data,
                                  map_id, map_data)

    return "未知的交互类型。"


def _interact_teleport(engine, lobby, player_name, player_data,
                       map_id, map_data):
    """传送阵交互 — 点亮 + 显示目的地"""
    discovered = player_data.setdefault('world', {}).setdefault(
        'teleports', [])
    just_lit = False
    if map_id not in discovered:
        discovered.append(map_id)
        just_lit = True
    discovered_set = set(discovered)
    dests = get_all_teleport_destinations(exclude_map=map_id)
    dests = [d for d in dests if d['id'] in discovered_set]

    def _build_menu(dests_):
        items = []
        for d in dests_:
            cost = teleport_cost(map_id, d['id'])
            items.append({
                'label': d['name'],
                'desc': f'{cost}G',
                'command': f"/_teleport {d['id']}",
            })
        return _menu_event('传送目的地', items)

    if just_lit:
        map_name = map_data.get('meta', {}).get('name', map_id)
        if not dests:
            return {
                'send_to_caller': [{'type': 'game',
                    'text': f"点亮了 {map_name} 的传送阵！"
                             "\n暂无其他已点亮的目的地。"}],
                'save': True,
            }
        menu = _build_menu(dests)
        menu['send_to_caller'].insert(0, {
            'type': 'game',
            'text': f"点亮了 {map_name} 的传送阵！",
        })
        menu['save'] = True
        return menu
    if not dests:
        return "暂无其他已点亮的目的地。"
    return _build_menu(dests)


def cmd_teleport(engine, lobby, player_name, player_data, args, map_id, map_data):
    """传送至目标地图 — 由传送阵子菜单触发"""
    pos = engine._positions[player_name]
    # 4 格内有传送阵即可（与 interact 半径一致）
    has_tp = any(
        abs(tx - pos[0]) <= 2 and abs(ty - pos[1]) <= 2
        for (tx, ty) in map_data.get('_teleport_map', {})
    )
    if not has_tp:
        return "附近没有传送阵。"
    target_id = (args or '').strip()
    if not target_id:
        return "传送目标无效。"

    parts = target_id.split()
    target_id = parts[0]
    confirmed = len(parts) > 1 and parts[1] == 'y'

    # 必须已点亮
    discovered = player_data.get('world', {}).get('teleports', [])
    if target_id not in discovered:
        return "你尚未点亮该传送阵。"
    target_map = load_map(target_id)
    if not target_map:
        return "目标地图不存在。"
    # 检查金币
    cost = teleport_cost(map_id, target_id)
    gold = player_data.get('gold', 0)
    if gold < cost:
        return f"金币不足（需要 {cost}G，当前 {gold}G）。"

    if cost > 0 and not confirmed:
        map_name = target_map.get('meta', {}).get('name', target_id)
        return _menu_event(f'确认传送至 {map_name}（{cost}G）？', [
            {'label': '确认传送', 'command': f'/_teleport {target_id} y'},
            {'label': '取消', 'command': ''},
        ])

    player_data['gold'] = gold - cost

    meta = target_map.get('meta', {})
    location = _derive_location(meta)
    spawn = list(target_map.get('spawn', [20, 14]))

    # 保存当前位置信息
    world = player_data.setdefault('world', {})
    world['town_pos'] = list(pos)
    world['town_map'] = map_id

    notify = engine._switch_map(player_name, target_id, spawn)
    lobby.set_player_location(player_name, location)
    engine._save_world_state(player_name, player_data, location)

    map_name = meta.get('name', target_id)
    map_update = engine._build_map_update(player_name)
    cost_text = f"（-{cost}G）" if cost > 0 else ""
    result = {
        'action': 'location_update',
        'send_to_caller': [
            map_update,
            {'type': 'game', 'text': f"传送至 {map_name}。{cost_text}"},
        ],
        'location': location,
        'save': True,
    }
    if notify:
        result['send_to_players'] = notify
    return result


from .fishing import cmd_fish, cmd_pull
from .recall import cmd_recall, cmd_recall_complete


SOCIAL_HANDLERS = {
    'enter': cmd_enter,
    'e': cmd_enter,
    'talk': cmd_talk,
    't': cmd_talk,
    'interact': cmd_interact,
    'i': cmd_interact,
    'user': cmd_user,
    'addfriend': cmd_addfriend,
    '_follow_player': cmd_follow_player,
    '_cancel_follow': cmd_cancel_follow,
    'fish': cmd_fish,
    'pull': cmd_pull,
    'recall': cmd_recall,
    '_recall_complete': cmd_recall_complete,
    '_teleport': cmd_teleport,
}

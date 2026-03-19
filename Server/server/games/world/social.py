"""社交与交互指令 — enter, talk, user, addfriend + 跟随机制

独立函数 + SOCIAL_HANDLERS 路由表，与 building_handlers.py 模式一致。
每个函数签名: cmd_X(engine, lobby, player_name, player_data, args, map_id, map_data)
"""

from __future__ import annotations

from ...systems.town_map import check_door, get_nearby_targets, is_walkable, load_map
from .building_handlers import _menu_event


def _check_on_door(map_data: dict, pos: list[int]) -> bool:
    """玩家是否站在门上"""
    return check_door(map_data, pos[0], pos[1]) is not None


def cmd_enter(engine, lobby, player_name, player_data, args, map_id, map_data):
    """进入/离开建筑 — 站在门上时切换地图"""
    pos = engine._positions[player_name]
    door = check_door(map_data, pos[0], pos[1])
    if not door:
        return "这里没有可通过的门。"
    location = door.get('location', '')
    building_id = door.get('building_id', '')
    if not location or not building_id:
        return "这扇门暂时无法通过。"

    current_location = lobby.get_player_location(player_name)

    if current_location == 'world_town':
        # 从城镇进入建筑
        indoor_map = load_map(building_id)
        if not indoor_map:
            return f"{door['name']} 暂时无法进入。"
        world = player_data.setdefault('world', {})
        world['town_pos'] = list(pos)
        world['town_map'] = map_id
        notify = engine._switch_map(player_name, building_id, indoor_map.get('spawn', [4, 4]))
        lobby.set_player_location(player_name, location)
        engine._save_world_state(player_name, player_data, location)
        building_name = door['name']
        map_update = engine._build_map_update(player_name)
        map_update.setdefault('room_data', {})['ai_description'] = f"玩家进入了{building_name}"
        result = {
            'action': 'location_update',
            'send_to_caller': [
                map_update,
                {'type': 'game', 'text': f"进入了 {building_name}。"},
            ],
            'location': location,
        }
        if notify:
            result['send_to_players'] = notify
        return result
    else:
        # 从建筑返回城镇
        world = player_data.get('world', {})
        town_map = world.get('town_map', 'starter_town')
        town_pos = world.get('town_pos', [20, 12])
        notify = engine._switch_map(player_name, town_map, town_pos)
        lobby.set_player_location(player_name, 'world_town')
        engine._save_world_state(player_name, player_data, 'world_town')
        map_update = engine._build_map_update(player_name)
        map_update.setdefault('room_data', {})['ai_description'] = '玩家离开建筑回到了城镇'
        result = {
            'action': 'location_update',
            'send_to_caller': [
                map_update,
                {'type': 'game', 'text': "回到了城镇。"},
            ],
            'location': 'world_town',
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
                return f"[{npc['name']}]: {dialog}" if dialog else f"{npc['name']} 沉默不语。"
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
        return "用法: addfriend <玩家名>"
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
            'action': 'follow_start',
            'send_to_caller': [
                engine._build_map_update(player_name),
                {'type': 'game', 'text': f"开始跟随 {target_name}。移动可取消跟随。"},
                {'type': 'game_event', 'game_type': 'world',
                 'event': 'follow_started', 'data': {'target': target_name}},
            ],
            'send_to_players': send_to_players,
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


SOCIAL_HANDLERS = {
    'enter': cmd_enter,
    'e': cmd_enter,
    'talk': cmd_talk,
    't': cmd_talk,
    'user': cmd_user,
    'addfriend': cmd_addfriend,
    '_follow_player': cmd_follow_player,
    '_cancel_follow': cmd_cancel_follow,
}

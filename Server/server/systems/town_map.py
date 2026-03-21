"""城镇地图引擎 — 加载地图、碰撞检测、移动、建筑进入判定

地图数据来自 JSON 文件。
每个地图有: 瓦片网格、建筑定义(门+NPC)、出生点。
玩家位置存储在 player_data['world']['pos']。
"""

from __future__ import annotations

import json
import os

_MAPS_DIR = os.path.join(os.path.dirname(__file__), '..', 'games', 'world', 'maps')

# 已加载地图缓存: {map_id: map_data}
_MAP_CACHE: dict[str, dict] = {}


def load_map(map_id: str) -> dict | None:
    """加载并缓存地图数据"""
    if map_id in _MAP_CACHE:
        return _MAP_CACHE[map_id]
    path = os.path.join(_MAPS_DIR, f'{map_id}.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # 预处理: 构建门位置 → 建筑的快速查找表
    door_map: dict[tuple[int, int], dict] = {}
    for bld_id, bld in data.get('buildings', {}).items():
        for dx, dy in bld.get('doors', []):
            door_map[(dx, dy)] = {
                'building_id': bld_id,
                'name': bld['name'],
                'location': bld.get('location', ''),
            }
    data['_door_map'] = door_map

    # 预处理: NPC 位置查找表
    npc_map: dict[tuple[int, int], dict] = {}
    for bld_id, bld in data.get('buildings', {}).items():
        npc = bld.get('npc')
        if npc:
            npc_map[(npc['pos'][0], npc['pos'][1])] = {
                'name': npc['name'],
                'building_id': bld_id,
            }
    for npc in data.get('npcs', []):
        npc_map[(npc['pos'][0], npc['pos'][1])] = {
            'id': npc.get('id', ''),
            'name': npc['name'],
            'dialog': npc.get('dialog', ''),
        }
    data['_npc_map'] = npc_map

    _MAP_CACHE[map_id] = data
    return data


def get_tile(map_data: dict, x: int, y: int) -> dict | None:
    """获取指定坐标的瓦片类型信息"""
    tiles = map_data.get('tiles', [])
    if y < 0 or y >= len(tiles):
        return None
    row = tiles[y]
    if x < 0 or x >= len(row):
        return None
    char = row[x]
    return map_data.get('tile_types', {}).get(char)


def is_walkable(map_data: dict, x: int, y: int) -> bool:
    """坐标是否可行走"""
    tile = get_tile(map_data, x, y)
    if not tile:
        return False
    return tile.get('walkable', False)


def move_player(map_data: dict, pos: list[int], dx: int, dy: int, steps: int = 1) -> tuple[list[int], str | None]:
    """移动玩家，返回 (新位置, 事件消息或None)

    逐步检测碰撞，遇到障碍物停下。
    经过门时触发建筑进入提示。
    """
    x, y = pos
    door_msg = None

    for _ in range(steps):
        nx, ny = x + dx, y + dy
        if not is_walkable(map_data, nx, ny):
            break
        x, y = nx, ny

        # 检查是否踩到门
        door_info = map_data.get('_door_map', {}).get((x, y))
        if door_info:
            door_msg = door_info['name']

    return [x, y], door_msg


def check_door(map_data: dict, x: int, y: int) -> dict | None:
    """检查当前位置是否在门上，返回建筑信息"""
    return map_data.get('_door_map', {}).get((x, y))


def check_npc(map_data: dict, x: int, y: int, dx: int, dy: int) -> dict | None:
    """检查面对方向是否有NPC"""
    return map_data.get('_npc_map', {}).get((x + dx, y + dy))


def get_nearby_targets(map_data: dict, x: int, y: int, radius: int = 2) -> list[dict]:
    """获取玩家周围指定半径内的所有可交互目标（NPC）

    范围为以玩家为中心的 (2*radius+1) x (2*radius+1) 区域。
    返回 [{'name': str, 'type': 'npc', ...}, ...]
    """
    npc_map = map_data.get('_npc_map', {})
    targets = []
    for (nx, ny), npc in npc_map.items():
        if abs(nx - x) <= radius and abs(ny - y) <= radius:
            targets.append({
                'name': npc['name'],
                'type': 'npc',
                'pos': [nx, ny],
            })
    return targets


def get_visible_region(map_data: dict, pos: list[int],
                       view_w: int | None = None, view_h: int | None = None,
                       other_players: list[dict] | None = None) -> dict:
    """获取以玩家为中心的可见区域数据

    返回:
    {
        'offset': [ox, oy],       # 视口左上角在地图中的坐标
        'tiles': [...],           # 裁剪后的瓦片行
        'player_vx': int,         # 玩家在视口中的 x
        'player_vy': int,         # 玩家在视口中的 y
        'npcs': [...],            # 视口内的 NPC 列表
        'buildings': [...],       # 视口内的建筑标签
    }
    """
    tiles = map_data.get('tiles', [])
    map_h = len(tiles)
    map_w = len(tiles[0]) if tiles else 0
    if view_w is None:
        view_w = map_w
    if view_h is None:
        view_h = map_h
    px, py = pos

    # 视口始终以玩家为中心（不做边界钳制）
    ox = px - view_w // 2
    oy = py - view_h // 2

    # 构建瓦片（地图外区域填充空白）
    pad_char = ' '
    visible_tiles = []
    for vy in range(view_h):
        my = oy + vy
        if 0 <= my < map_h:
            row = tiles[my]
            line = ''
            for vx in range(view_w):
                mx = ox + vx
                if 0 <= mx < len(row):
                    line += row[mx]
                else:
                    line += pad_char
            visible_tiles.append(line)
        else:
            visible_tiles.append(pad_char * view_w)

    # 收集视口内 NPC（ox/oy 可能为负数，只要映射后在 0..view 范围内即可）
    visible_npcs = []
    for bld_id, bld in map_data.get('buildings', {}).items():
        npc = bld.get('npc')
        if npc:
            nx, ny = npc['pos']
            vx, vy = nx - ox, ny - oy
            if 0 <= vx < view_w and 0 <= vy < view_h:
                visible_npcs.append({
                    'x': vx, 'y': vy,
                    'char': npc['char'], 'color': npc['color'],
                    'name': npc['name'],
                })
    for npc in map_data.get('npcs', []):
        nx, ny = npc['pos']
        vx, vy = nx - ox, ny - oy
        if 0 <= vx < view_w and 0 <= vy < view_h:
            visible_npcs.append({
                'x': vx, 'y': vy,
                'char': npc['char'], 'color': npc['color'],
                'name': npc['name'],
            })

    # 收集视口内其他玩家
    visible_players = []
    if other_players:
        for p in other_players:
            pvx, pvy = p['x'] - ox, p['y'] - oy
            if 0 <= pvx < view_w and 0 <= pvy < view_h:
                visible_players.append({
                    'x': pvx, 'y': pvy,
                    'name': p['name'],
                })

    return {
        'offset': [ox, oy],
        'tiles': visible_tiles,
        'player_vx': px - ox,
        'player_vy': py - oy,
        'npcs': visible_npcs,
        'players': visible_players,
        'tile_types': map_data.get('tile_types', {}),
        'map_name': map_data.get('meta', {}).get('name', ''),
        'map_w': map_w,
        'map_h': map_h,
    }

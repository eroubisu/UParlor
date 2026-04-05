"""城镇地图引擎 — 加载地图、碰撞检测、移动、建筑进入判定

地图数据来自 JSON 文件。
每个地图有: 瓦片网格、建筑定义(门+NPC)、出生点。
玩家位置存储在 player_data['world']['pos']。
"""

from __future__ import annotations

import json
import os
import random
import time

from ...config import OUTDOOR_MAP_TYPES

_MAPS_DIR = os.path.join(os.path.dirname(__file__), 'data', 'maps')
_NPC_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), 'data', 'npc_registry.json')

# 已加载地图缓存: {map_id: map_data}
_MAP_CACHE: dict[str, dict] = {}

# NPC 注册表缓存: {npc_id: {name, char, color, dialog, ...}}
_NPC_REGISTRY: dict[str, dict] | None = None


def _get_npc_registry() -> dict[str, dict]:
    global _NPC_REGISTRY
    if _NPC_REGISTRY is None:
        if os.path.exists(_NPC_REGISTRY_PATH):
            with open(_NPC_REGISTRY_PATH, 'r', encoding='utf-8') as f:
                _NPC_REGISTRY = json.load(f)
        else:
            _NPC_REGISTRY = {}
    return _NPC_REGISTRY


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
        # 解析目标地图的显示名称
        name = bld.get('name', bld_id)
        target_path = os.path.join(_MAPS_DIR, f'{bld_id}.json')
        if os.path.exists(target_path):
            try:
                with open(target_path, 'r', encoding='utf-8') as tf:
                    target_meta = json.load(tf).get('meta', {})
                name = target_meta.get('name', name)
            except Exception:
                pass
        for dx, dy in bld.get('doors', []):
            door_map[(dx, dy)] = {
                'building_id': bld_id,
                'name': name,
            }
    data['_door_map'] = door_map

    # 预处理: NPC 位置查找表 (从注册表合并属性)
    npc_map: dict[tuple[int, int], dict] = {}
    registry = _get_npc_registry()
    for npc in data.get('npcs', []):
        npc_id = npc.get('id', '')
        reg = registry.get(npc_id, {})
        entry = {
            'id': npc_id,
            'name': npc.get('name') or reg.get('name', npc_id),
            'dialog': npc.get('dialog') or reg.get('dialog', ''),
            'char': npc.get('char') or reg.get('char', '*'),
            'color': npc.get('color') or reg.get('color', '#808080'),
            'patrol_radius': npc.get('patrol_radius', reg.get('patrol_radius', 0)),
        }
        npc_map[(npc['pos'][0], npc['pos'][1])] = entry
    data['_npc_map'] = npc_map

    # 预处理: 告示牌位置查找表
    sign_map: dict[tuple[int, int], str] = {}
    for s in data.get('signs', []):
        sign_map[(s['pos'][0], s['pos'][1])] = s.get('text', '')
    data['_sign_map'] = sign_map

    # 预处理: 传送点位置查找表（从 % 瓦片自动构建）
    tp_map: dict[tuple[int, int], dict] = {}
    for y, row in enumerate(data.get('tiles', [])):
        for x, ch in enumerate(row):
            if ch == '%':
                tp_map[(x, y)] = {}
    data['_teleport_map'] = tp_map

    _MAP_CACHE[map_id] = data
    return data


# 传送目的地缓存（服务器启动后首次调用时构建）
_TELEPORT_DESTS: list[dict] | None = None


def get_all_teleport_destinations(exclude_map: str = '') -> list[dict]:
    """返回有传送阵的 world/road/site 目的地列表（缓存）"""
    global _TELEPORT_DESTS
    if _TELEPORT_DESTS is None:
        dests = []
        for fname in os.listdir(_MAPS_DIR):
            if not fname.endswith('.json'):
                continue
            mid = fname[:-5]
            fpath = os.path.join(_MAPS_DIR, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue
            meta = data.get('meta', {})
            mt = meta.get('map_type', '')
            if mt not in OUTDOOR_MAP_TYPES:
                continue
            has_portal = any('%' in row for row in data.get('tiles', []))
            if not has_portal:
                continue
            dests.append({
                'id': mid,
                'name': meta.get('name', mid),
                'map_type': mt,
            })
        dests.sort(key=lambda d: d['name'])
        _TELEPORT_DESTS = dests
    if not exclude_map:
        return _TELEPORT_DESTS
    return [d for d in _TELEPORT_DESTS if d['id'] != exclude_map]


# ── 地图拓扑距离（BFS）──

_TOPO_GRAPH: dict[str, set[str]] | None = None

_TELEPORT_COST_PER_HOP = 50  # 每跳 50 金币


def _build_topo_graph() -> dict[str, set[str]]:
    """构建地图连通图: map_id → {neighbor_ids}"""
    global _TOPO_GRAPH
    if _TOPO_GRAPH is not None:
        return _TOPO_GRAPH
    graph: dict[str, set[str]] = {}
    for fname in os.listdir(_MAPS_DIR):
        if not fname.endswith('.json'):
            continue
        mid = fname[:-5]
        fpath = os.path.join(_MAPS_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        neighbors = set(data.get('buildings', {}).keys())
        graph[mid] = neighbors
        # 保证双向
        for nb in neighbors:
            graph.setdefault(nb, set()).add(mid)
    _TOPO_GRAPH = graph
    return graph


def teleport_cost(src_map: str, dst_map: str) -> int:
    """BFS 计算两地图之间的拓扑距离，乘以单跳费用"""
    if src_map == dst_map:
        return 0
    graph = _build_topo_graph()
    visited = {src_map}
    queue = [(src_map, 0)]
    while queue:
        current, dist = queue.pop(0)
        for nb in graph.get(current, ()):
            if nb == dst_map:
                return (dist + 1) * _TELEPORT_COST_PER_HOP
            if nb not in visited:
                visited.add(nb)
                queue.append((nb, dist + 1))
    # 不可达，返回高价
    return 10 * _TELEPORT_COST_PER_HOP


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


def get_tile_cd_mult(map_data: dict, x: int, y: int) -> float:
    """获取地形移动冷却倍率 (1.0=正常, >1 更慢)"""
    tile = get_tile(map_data, x, y)
    if not tile:
        return 1.0
    return tile.get('cd_mult', 1.0)


def get_tile_damage(map_data: dict, x: int, y: int) -> int:
    """获取地块每步伤害 (0=无伤害)"""
    tile = get_tile(map_data, x, y)
    if not tile:
        return 0
    return tile.get('damage', 0)


def is_concealed(map_data: dict, x: int, y: int) -> bool:
    """玩家在此坐标是否处于隐蔽状态"""
    tile = get_tile(map_data, x, y)
    if not tile:
        return False
    return bool(tile.get('concealment'))


def is_near_water(map_data: dict, x: int, y: int, radius: int = 1) -> bool:
    """检查周围是否有水 (通过 tile 的 water 属性判断)"""
    tiles = map_data.get('tiles', [])
    tile_types = map_data.get('tile_types', {})
    for dy in range(-radius, radius + 1):
        my = y + dy
        if my < 0 or my >= len(tiles):
            continue
        row = tiles[my]
        for dx in range(-radius, radius + 1):
            mx = x + dx
            if 0 <= mx < len(row):
                info = tile_types.get(row[mx])
                if info and info.get('water'):
                    return True
    return False


# ── NPC 巡逻运行时 ──

# {map_id: {npc_id: [x, y]}} — 可变的 NPC 运行时位置
_npc_positions: dict[str, dict[str, list[int]]] = {}
# {map_id: float} — 上次巡逻时间
_npc_last_patrol: dict[str, float] = {}


def _init_npc_runtime(map_id: str, map_data: dict):
    """初始化地图 NPC 运行时位置（仅首次）"""
    if map_id in _npc_positions:
        return
    rt: dict[str, list[int]] = {}
    for npc in map_data.get('npcs', []):
        npc_id = npc.get('id', '')
        if npc_id:
            rt[npc_id] = list(npc['pos'])
    _npc_positions[map_id] = rt
    _npc_last_patrol[map_id] = time.monotonic()


def get_npc_pos(map_id: str, npc_id: str, fallback: list[int]) -> list[int]:
    """获取 NPC 运行时位置"""
    return _npc_positions.get(map_id, {}).get(npc_id, fallback)


def move_npcs_if_due(map_id: str, map_data: dict,
                     player_positions: dict[str, list[int]] | None = None
                     ) -> list[dict]:
    """检查并移动 NPC（搭便车式，由玩家移动触发）

    返回移动了的 NPC 列表: [{'id': str, 'old': [x,y], 'new': [x,y], 'npc': dict}]
    """
    _init_npc_runtime(map_id, map_data)
    now = time.monotonic()
    last = _npc_last_patrol.get(map_id, 0.0)
    if now - last < 5.0:
        return []
    _npc_last_patrol[map_id] = now

    moves = []
    rt = _npc_positions[map_id]
    registry = _get_npc_registry()
    occupied = set()
    if player_positions:
        occupied.update((p[0], p[1]) for p in player_positions.values())
    for npc_id, pos in rt.items():
        occupied.add((pos[0], pos[1]))

    for npc in map_data.get('npcs', []):
        npc_id = npc.get('id', '')
        if not npc_id:
            continue
        reg = registry.get(npc_id, {})
        patrol_r = npc.get('patrol_radius', reg.get('patrol_radius', 0))
        if patrol_r <= 0:
            continue
        cur = rt.get(npc_id, npc['pos'])
        home = npc['pos']
        # 随机方向
        dx, dy = random.choice([(0, 1), (0, -1), (1, 0), (-1, 0)])
        nx, ny = cur[0] + dx, cur[1] + dy
        # 不超出巡逻范围
        if abs(nx - home[0]) > patrol_r or abs(ny - home[1]) > patrol_r:
            continue
        # 不走进不可行走区域
        if not is_walkable(map_data, nx, ny):
            continue
        # 不走到其他 NPC 或玩家位置
        if (nx, ny) in occupied:
            continue
        old = list(cur)
        rt[npc_id] = [nx, ny]
        occupied.discard((cur[0], cur[1]))
        occupied.add((nx, ny))
        reg_entry = registry.get(npc_id, {})
        moves.append({
            'id': npc_id, 'old': old, 'new': [nx, ny],
            'name': npc.get('name') or reg_entry.get('name', npc_id),
            'char': npc.get('char') or reg_entry.get('char', '*'),
            'color': npc.get('color') or reg_entry.get('color', '#808080'),
        })
    # 更新 _npc_map 以反映新位置
    if moves:
        _refresh_npc_map(map_data, map_id)
    return moves


def _refresh_npc_map(map_data: dict, map_id: str):
    """根据运行时位置更新 _npc_map"""
    rt = _npc_positions.get(map_id, {})
    npc_map: dict[tuple[int, int], dict] = {}
    registry = _get_npc_registry()
    # 自由 NPC（使用运行时位置，从注册表合并属性）
    for npc in map_data.get('npcs', []):
        npc_id = npc.get('id', '')
        reg = registry.get(npc_id, {})
        pos = rt.get(npc_id, npc['pos'])
        npc_map[(pos[0], pos[1])] = {
            'id': npc_id,
            'name': npc.get('name') or reg.get('name', npc_id),
            'dialog': npc.get('dialog') or reg.get('dialog', ''),
            'char': npc.get('char') or reg.get('char', '*'),
            'color': npc.get('color') or reg.get('color', '#808080'),
            'patrol_radius': npc.get('patrol_radius', reg.get('patrol_radius', 0)),
        }
    map_data['_npc_map'] = npc_map


def cleanup_map_runtime(map_id: str):
    """清理地图的 NPC 运行时状态（当地图上无玩家时调用）"""
    _npc_positions.pop(map_id, None)
    _npc_last_patrol.pop(map_id, None)


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


def get_door(map_data: dict, x: int, y: int) -> dict | None:
    """检查当前位置是否在门上，返回建筑信息"""
    return map_data.get('_door_map', {}).get((x, y))


def get_npc(map_data: dict, x: int, y: int, dx: int, dy: int) -> dict | None:
    """检查面对方向是否有NPC"""
    return map_data.get('_npc_map', {}).get((x + dx, y + dy))


def get_sign(map_data: dict, x: int, y: int, dx: int, dy: int) -> str | None:
    """检查当前位置或面朝方向是否有告示牌，返回文本"""
    sm = map_data.get('_sign_map', {})
    text = sm.get((x, y)) or sm.get((x + dx, y + dy))
    return text or None


def get_teleport(map_data: dict, x: int, y: int) -> dict | None:
    """检查当前位置是否有传送点"""
    return map_data.get('_teleport_map', {}).get((x, y))


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


def get_nearby_interactables(map_data: dict, x: int, y: int,
                             radius: int = 2) -> list[dict]:
    """获取周围所有可交互对象 (告示牌、传送阵)"""
    results: list[dict] = []
    r = radius
    # 告示牌
    for (sx, sy), text in map_data.get('_sign_map', {}).items():
        if abs(sx - x) <= r and abs(sy - y) <= r and text:
            preview = text[:8] + '…' if len(text) > 8 else text
            results.append({'name': '告示牌', 'type': 'sign',
                            'pos': [sx, sy], 'text': text, 'desc': preview})
    # 传送阵
    for (tx, ty) in map_data.get('_teleport_map', {}):
        if abs(tx - x) <= r and abs(ty - y) <= r:
            results.append({'name': '传送阵', 'type': 'teleport',
                            'pos': [tx, ty]})
    return results


def get_visible_region(map_data: dict, pos: list[int],
                       view_w: int | None = None, view_h: int | None = None,
                       other_players: list[dict] | None = None,
                       map_id: str | None = None) -> dict:
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

    # 视野限制: default_visibility 存在时遮罩超出范围的地块
    vis_range = map_data.get('meta', {}).get('default_visibility')
    if vis_range is not None:
        player_vx = px - ox
        player_vy = py - oy
        masked = []
        for vy_idx, row in enumerate(visible_tiles):
            chars = list(row)
            for vx_idx in range(len(chars)):
                if abs(vx_idx - player_vx) + abs(vy_idx - player_vy) > vis_range:
                    chars[vx_idx] = ' '
            masked.append(''.join(chars))
        visible_tiles = masked

    # 收集视口内 NPC（从 _npc_map 读取已合并注册表的数据）
    visible_npcs = []
    npc_map = map_data.get('_npc_map', {})
    for (nx, ny), npc_info in npc_map.items():
        vx, vy = nx - ox, ny - oy
        if 0 <= vx < view_w and 0 <= vy < view_h:
            if vis_range is not None and abs(vx - (px - ox)) + abs(vy - (py - oy)) > vis_range:
                continue
            visible_npcs.append({
                'x': vx, 'y': vy,
                'char': npc_info.get('char', '*'),
                'color': npc_info.get('color', '#808080'),
                'name': npc_info.get('name', ''),
            })

    # 收集视口内其他玩家（隐蔽地块上的玩家不可见）
    visible_players = []
    if other_players:
        for p in other_players:
            if is_concealed(map_data, p['x'], p['y']):
                continue
            pvx, pvy = p['x'] - ox, p['y'] - oy
            if 0 <= pvx < view_w and 0 <= pvy < view_h:
                if vis_range is not None and abs(pvx - (px - ox)) + abs(pvy - (py - oy)) > vis_range:
                    continue
                visible_players.append({
                    'x': pvx, 'y': pvy,
                    'name': p['name'],
                })

    return {
        'offset': [ox, oy],
        'tiles': visible_tiles,
        'player_vx': px - ox,
        'player_vy': py - oy,
        'concealed': is_concealed(map_data, pos[0], pos[1]),
        'npcs': visible_npcs,
        'players': visible_players,
        'tile_types': map_data.get('tile_types', {}),
        'map_name': map_data.get('meta', {}).get('name', ''),
        'map_w': map_w,
        'map_h': map_h,
    }

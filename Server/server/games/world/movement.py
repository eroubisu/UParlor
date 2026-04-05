"""移动系统 — 冷却、视口、增量广播

混入 WorldEngine，提供移动冷却计算、视口范围查询和增量更新构建。
"""

from __future__ import annotations

import time

from ...msg_types import ROOM_UPDATE
from ...config import DEFAULT_MAP
from .town_map import load_map, get_visible_region, get_door, get_tile, get_tile_cd_mult, is_concealed
from ...systems.attributes import get_total_stats

# 方向映射: hjkl → (dx, dy)
_DIRECTIONS = {
    'h': (-1, 0),
    'j': (0, 1),
    'k': (0, -1),
    'l': (1, 0),
}

# 移动冷却
_BASE_COOLDOWN = 0.32  # 320ms
_MIN_COOLDOWN = 0.08   # 80ms 下限


class MovementMixin:
    """移动与视口工具方法 — 混入 WorldEngine

    依赖 FollowMixin._get_followers_recursive（用于链冷却计算和 delta 跳过）。
    """

    def _get_move_cooldown(self, player_data: dict,
                           map_data: dict | None = None,
                           pos: list[int] | None = None) -> float:
        """计算移动冷却时间（考虑速度加成 + 地形倍率）"""
        stats = get_total_stats(player_data)
        agility = stats.get('agility', 10)
        bonus = max(0, agility - 10)
        terrain = 1.0
        if map_data and pos:
            terrain = get_tile_cd_mult(map_data, pos[0], pos[1])
        cd = _BASE_COOLDOWN * terrain * (1.0 - bonus * 0.01)
        return max(_MIN_COOLDOWN, cd)

    def _check_cooldown(self, player_name: str, player_data: dict,
                         map_data: dict | None = None,
                         pos: list[int] | None = None) -> bool:
        """检查移动冷却，返回 True=可移动（snap-to-grid 保证均匀节奏）"""
        now = time.monotonic()
        last = self._last_move.get(player_name, 0.0)
        cd = self._get_chain_cooldown(player_name, player_data, map_data, pos)
        if now - last < cd - 0.03:
            return False
        expected = last + cd
        self._last_move[player_name] = expected if now - expected < cd else now
        return True

    def _get_chain_cooldown(self, player_name: str, player_data: dict,
                            map_data: dict | None = None,
                            pos: list[int] | None = None) -> float:
        """计算考虑跟随链后的实际冷却（取链中最慢者）"""
        cd = self._get_move_cooldown(player_data, map_data, pos)
        self._cooldowns[player_name] = cd
        followers = self._get_followers_recursive(player_name)
        if not followers:
            return cd
        slowest = cd
        for fname in followers:
            slowest = max(slowest, self._cooldowns.get(fname, _BASE_COOLDOWN))
        return slowest

    # ── 视口 & 空间查询 ──

    def _player_viewport_range(self, name: str):
        """返回玩家视口的世界坐标范围 (x1, y1, x2, y2)"""
        pos = self._positions.get(name)
        vp = self._viewports.get(name)
        if not pos or not vp:
            return None
        vw, vh = vp
        ox = pos[0] - vw // 2
        oy = pos[1] - vh // 2
        return (ox, oy, ox + vw, oy + vh)

    @staticmethod
    def _in_viewport(vr: tuple, x: int, y: int) -> bool:
        return vr[0] <= x < vr[2] and vr[1] <= y < vr[3]

    def _get_nearby_players(self, player_name: str, radius: int = 2) -> list[str]:
        """获取指定半径内的其他在线玩家"""
        map_id = self._maps.get(player_name)
        pos = self._positions.get(player_name)
        if not map_id or not pos:
            return []
        result = []
        for name in self._map_players.get(map_id, ()):
            if name == player_name:
                continue
            p = self._positions.get(name)
            if p and abs(p[0] - pos[0]) <= radius and abs(p[1] - pos[1]) <= radius:
                result.append(name)
        return result

    # ── 地图更新构建 ──

    def _build_map_update(self, player_name: str) -> dict:
        """构建完整地图更新消息（用于初次加载/视口变化）"""
        map_id = self._maps.get(player_name, DEFAULT_MAP)
        map_data = load_map(map_id)
        pos = self._positions.get(player_name, [20, 14])
        vp = self._viewports.get(player_name)
        view_w = vp[0] if vp else None
        view_h = vp[1] if vp else None

        other_players = []
        for name in self._map_players.get(map_id, ()):
            if name != player_name:
                p = self._positions.get(name)
                if p:
                    other_players.append({'x': p[0], 'y': p[1], 'name': name})

        view = get_visible_region(map_data, pos, view_w, view_h, other_players,
                                   map_id=map_id)
        door = get_door(map_data, pos[0], pos[1])

        tile = get_tile(map_data, pos[0], pos[1])
        tile_name = tile.get('name', '') if tile else ''

        move_cd = self._cooldowns.get(player_name, _BASE_COOLDOWN)

        return {
            'type': ROOM_UPDATE,
            'room_data': {
                'game_type': 'world',
                'state': 'exploring',
                'map': view,
                'door': {'name': door['name'], 'building_id': door['building_id']} if door else None,
                'pos': pos,
                'tile_name': tile_name,
                'move_cd': round(move_cd, 3),
            },
        }

    def _build_player_delta(self, player_name: str, old_pos: list[int],
                            new_pos: list[int], map_id: str) -> dict:
        """为同地图其他玩家构建增量更新（只发移动者的 delta）

        跳过正在跟随移动者的玩家（他们会收到自己的 ROOM_UPDATE）。
        """
        updates: dict[str, list] = {}
        chain_followers = self._get_followers_recursive(player_name)
        map_data = load_map(map_id)
        # 隐蔽地块上的玩家对其他人不可见
        was_concealed = is_concealed(map_data, old_pos[0], old_pos[1])
        now_concealed = is_concealed(map_data, new_pos[0], new_pos[1])
        for name in self._map_players.get(map_id, ()):
            if name == player_name or name in chain_followers:
                continue
            vr = self._player_viewport_range(name)
            if not vr:
                continue
            old_in = self._in_viewport(vr, old_pos[0], old_pos[1]) and not was_concealed
            new_in = self._in_viewport(vr, new_pos[0], new_pos[1]) and not now_concealed
            if not old_in and not new_in:
                continue
            obs_pos = self._positions.get(name, [0, 0])
            obs_vp = self._viewports.get(name, (0, 0))
            obs_ox = obs_pos[0] - obs_vp[0] // 2
            obs_oy = obs_pos[1] - obs_vp[1] // 2
            if new_in and not old_in:
                evt_type = 'player_entered'
            elif old_in and not new_in:
                evt_type = 'player_left'
            else:
                evt_type = 'player_moved'
            delta = {
                'type': 'game_event',
                'game_type': 'world',
                'event': evt_type,
                'data': {
                    'name': player_name,
                    'x': new_pos[0] - obs_ox,
                    'y': new_pos[1] - obs_oy,
                },
            }
            updates[name] = [delta]
        return updates

"""跟随系统 — 跟随/取消跟随和 BFS 链式移动

混入 WorldEngine，提供玩家间的跟随关系管理和链式移动。
"""

from __future__ import annotations


class FollowMixin:
    """跟随系统方法 — 混入 WorldEngine

    依赖 MovementMixin._build_player_delta / _build_map_update（用于跟随者移动广播）。
    """

    def _get_followers_recursive(self, name: str) -> set[str]:
        """递归获取所有跟随者（含跟随者的跟随者）"""
        result: set[str] = set()
        direct = self._followers.get(name, set())
        for f in direct:
            result.add(f)
            result.update(self._get_followers_recursive(f))
        return result

    def _follow(self, follower: str, leader: str):
        """建立跟随关系"""
        self._unfollow(follower)
        self._following[follower] = leader
        self._followers.setdefault(leader, set()).add(follower)

    def _unfollow(self, player_name: str):
        """解除跟随关系"""
        old_leader = self._following.pop(player_name, None)
        if old_leader and old_leader in self._followers:
            self._followers[old_leader].discard(player_name)
            if not self._followers[old_leader]:
                del self._followers[old_leader]

    def _move_followers(self, leader: str, old_leader_pos: list[int], map_id: str) -> dict:
        """BFS 逐层移动跟随者，每人移到其直接领队的旧位置（串成一列）"""
        send_to: dict[str, list] = {}
        queue = []
        for f in self._followers.get(leader, ()):
            if self._maps.get(f) == map_id:
                queue.append((f, old_leader_pos))
        while queue:
            next_queue = []
            for fname, target_pos in queue:
                fold = list(self._positions.get(fname, target_pos))
                self._positions[fname] = list(target_pos)
                for ff in self._followers.get(fname, ()):
                    if self._maps.get(ff) == map_id:
                        next_queue.append((ff, fold))
                fdelta = self._build_player_delta(fname, fold, target_pos, map_id)
                for target, msgs in fdelta.items():
                    send_to.setdefault(target, []).extend(msgs)
                send_to.setdefault(fname, []).append(self._build_map_update(fname))
            queue = next_queue
        return send_to

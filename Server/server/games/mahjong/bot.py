"""麻将机器人 AI — 封装所有 bot 决策逻辑

职责:
- choose_discard(room, seat): 选择打哪张牌
- should_tsumo(room, seat): 是否自摸和牌
- respond_to_discard(room, seat, tile): 对别人的弃牌做出响应 (ron/pon/chi/pass)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mahjong.shanten import Shanten

if TYPE_CHECKING:
    from .room import MahjongRoom

_shanten = Shanten()


class MahjongBot:
    """麻将 bot 决策器

    策略:
    - 向听数最小化的贪心打牌
    - 和牌判定: 无条件接受 (ron/tsumo)
    - 碰: 碰后向听数不增加时执行
    - 吃: 吃后向听数不增加时执行
    - 立直中只自摸不副露
    """

    # ── 和牌 ──

    def should_tsumo(self, room: MahjongRoom, seat: int) -> dict | None:
        """检查是否应该自摸，返回 win_info 或 None"""
        if room.drawn_tile is None:
            return None
        win_info = room.check_tsumo(seat)
        if win_info and win_info.get('han', 0) >= 1:
            return win_info
        return None

    # ── 对别人弃牌的响应 ──

    def respond_to_discard(self, room: MahjongRoom, seat: int,
                           tile: int, from_seat: int) -> str:
        """对其他玩家的弃牌做出响应

        返回: 'ron' / 'pon' / 'chi' / 'pass'
        """
        # 立直中: 只考虑和牌
        if room.riichi[seat]:
            if room.check_ron(seat, tile) is not None:
                return 'ron'
            return 'pass'

        # 优先荣和
        if room.check_ron(seat, tile) is not None:
            return 'ron'

        # 碰: 碰后向听数不增加
        if room.can_pon(seat, tile):
            if self._should_pon(room, seat, tile):
                return 'pon'

        # 吃: 吃后向听数不增加
        if room.can_chi(seat, tile, from_seat):
            combo = self._best_chi_combo(room, seat, tile)
            if combo:
                return 'chi'

        return 'pass'

    # ── 打牌 ──

    def choose_discard(self, room: MahjongRoom, seat: int) -> int:
        """选择弃牌，返回 tile_136"""
        hand = room.get_full_hand(seat)
        if not hand:
            return -1
        return self._best_discard(hand)

    # ── 吃的组合选择 ──

    def best_chi_combo(self, room: MahjongRoom, seat: int,
                       tile: int) -> list[int] | None:
        """返回吃的最佳组合 (两张手牌), 或 None"""
        return self._best_chi_combo(room, seat, tile)

    # ── 内部策略 ──

    def _best_discard(self, hand: list[int]) -> int:
        """向听数最小化贪心"""
        best_tile = hand[-1]
        best_shanten = 99
        for t in hand:
            test = [x for x in hand if x != t]
            tiles_34 = [0] * 34
            for x in test:
                tiles_34[x // 4] += 1
            try:
                sh = _shanten.calculate_shanten(tiles_34)
                if sh < best_shanten:
                    best_shanten = sh
                    best_tile = t
            except Exception:
                pass
        return best_tile

    def _should_pon(self, room: MahjongRoom, seat: int, tile: int) -> bool:
        """碰后向听数是否不增加"""
        hand = list(room.hands[seat])
        # 当前向听数
        cur_34 = [0] * 34
        for t in hand:
            cur_34[t // 4] += 1
        try:
            cur_sh = _shanten.calculate_shanten(cur_34)
        except Exception:
            return False

        # 模拟碰后: 移除手中两张同种牌, 然后打出最优牌
        tile_34 = tile // 4
        sim_hand = list(hand)
        removed = 0
        for t in list(sim_hand):
            if t // 4 == tile_34 and removed < 2:
                sim_hand.remove(t)
                removed += 1
        if removed < 2:
            return False

        # 碰后需要打一张 — 找最优弃牌后的向听数
        best_sh = 99
        for t in sim_hand:
            test = [x for x in sim_hand if x != t]
            test_34 = [0] * 34
            for x in test:
                test_34[x // 4] += 1
            try:
                sh = _shanten.calculate_shanten(test_34)
                if sh < best_sh:
                    best_sh = sh
            except Exception:
                pass

        return best_sh <= cur_sh

    def _best_chi_combo(self, room: MahjongRoom, seat: int,
                        tile: int) -> list[int] | None:
        """选择最优吃组合, 返回两张手牌或 None

        只在吃后向听数不增加时返回组合。
        """
        tile_34 = tile // 4
        if tile_34 >= 27:
            return None
        suit_base = (tile_34 // 9) * 9
        num = tile_34 - suit_base
        hand = room.hands[seat]

        # 当前向听数
        cur_34 = [0] * 34
        for t in hand:
            cur_34[t // 4] += 1
        try:
            cur_sh = _shanten.calculate_shanten(cur_34)
        except Exception:
            return None

        # 枚举所有可能的顺子组合
        candidates = []
        # tile-2, tile-1, tile
        if num >= 2:
            a, b = tile_34 - 2, tile_34 - 1
            t_a = self._find_tile(hand, a)
            t_b = self._find_tile(hand, b)
            if t_a is not None and t_b is not None:
                candidates.append([t_a, t_b])
        # tile-1, tile, tile+1
        if 1 <= num <= 7:
            a, b = tile_34 - 1, tile_34 + 1
            t_a = self._find_tile(hand, a)
            t_b = self._find_tile(hand, b)
            if t_a is not None and t_b is not None:
                candidates.append([t_a, t_b])
        # tile, tile+1, tile+2
        if num <= 6:
            a, b = tile_34 + 1, tile_34 + 2
            t_a = self._find_tile(hand, a)
            t_b = self._find_tile(hand, b)
            if t_a is not None and t_b is not None:
                candidates.append([t_a, t_b])

        if not candidates:
            return None

        # 选向听数最低的组合
        best_combo = None
        best_sh = 99
        for combo in candidates:
            sim_hand = list(hand)
            for t in combo:
                sim_hand.remove(t)
            # 吃后要打一张
            for discard in sim_hand:
                test = [x for x in sim_hand if x != discard]
                test_34 = [0] * 34
                for x in test:
                    test_34[x // 4] += 1
                try:
                    sh = _shanten.calculate_shanten(test_34)
                    if sh < best_sh:
                        best_sh = sh
                        best_combo = combo
                except Exception:
                    pass

        if best_combo is not None and best_sh <= cur_sh:
            return best_combo
        return None

    @staticmethod
    def _find_tile(hand: list[int], tile_34: int) -> int | None:
        """在手牌中找一张 tile_34 对应的 136 编码牌"""
        for t in hand:
            if t // 4 == tile_34:
                return t
        return None

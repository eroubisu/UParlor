"""斗地主牌型识别测试"""

from __future__ import annotations

import pytest

from server.games.cards.deck import Card
from server.games.doudizhu.patterns import (
    BOMB, FOUR_2, PAIR, PASS, PLANE, PLANE_1, PLANE_2,
    ROCKET, SINGLE, STRAIGHT, STRAIGHT_PAIR, TRIPLE, TRIPLE_1, TRIPLE_2,
    Play, doudizhu_rank, identify, sort_hand,
)


def _c(rank: int, suit: int = 0) -> Card:
    return Card(suit=suit, rank=rank)


def _hand(*ranks: int) -> list[Card]:
    """从 rank 列表构造手牌(suit 递增以区分)"""
    return [_c(r, i % 4) for i, r in enumerate(ranks)]


class TestDoudizhuRank:
    """斗地主权重映射"""

    def test_normal_cards(self):
        assert doudizhu_rank(_c(3)) == 3
        assert doudizhu_rank(_c(13)) == 13  # K
        assert doudizhu_rank(_c(14)) == 14  # A

    def test_two_is_highest_normal(self):
        assert doudizhu_rank(_c(2)) == 15

    def test_jokers(self):
        assert doudizhu_rank(_c(15, -1)) == 16  # 小王
        assert doudizhu_rank(_c(16, -2)) == 17  # 大王


class TestIdentifySingle:
    """基础牌型识别"""

    def test_pass(self):
        play = identify([])
        assert play.type_id == PASS

    def test_single(self):
        play = identify(_hand(5))
        assert play.type_id == SINGLE

    def test_pair(self):
        play = identify([_c(7, 0), _c(7, 1)])
        assert play.type_id == PAIR

    def test_triple(self):
        play = identify([_c(9, 0), _c(9, 1), _c(9, 2)])
        assert play.type_id == TRIPLE

    def test_triple_with_one(self):
        play = identify([_c(9, 0), _c(9, 1), _c(9, 2), _c(3, 0)])
        assert play.type_id == TRIPLE_1

    def test_triple_with_pair(self):
        play = identify([_c(9, 0), _c(9, 1), _c(9, 2), _c(3, 0), _c(3, 1)])
        assert play.type_id == TRIPLE_2


class TestIdentifySequences:
    """顺子/连对/飞机"""

    def test_straight_five(self):
        play = identify(_hand(3, 4, 5, 6, 7))
        assert play.type_id == STRAIGHT
        assert play.length == 5

    def test_straight_rejects_two(self):
        """顺子不能包含 2"""
        play = identify(_hand(10, 11, 12, 13, 2))
        assert play is None  # 10-A-2 不连续

    def test_straight_pair(self):
        play = identify([
            _c(5, 0), _c(5, 1), _c(6, 0), _c(6, 1), _c(7, 0), _c(7, 1)])
        assert play.type_id == STRAIGHT_PAIR
        assert play.length == 3

    def test_plane(self):
        play = identify([
            _c(8, 0), _c(8, 1), _c(8, 2),
            _c(9, 0), _c(9, 1), _c(9, 2)])
        assert play.type_id == PLANE

    def test_plane_with_singles(self):
        play = identify([
            _c(8, 0), _c(8, 1), _c(8, 2),
            _c(9, 0), _c(9, 1), _c(9, 2),
            _c(3, 0), _c(4, 0)])
        assert play.type_id == PLANE_1

    def test_plane_with_pairs(self):
        play = identify([
            _c(8, 0), _c(8, 1), _c(8, 2),
            _c(9, 0), _c(9, 1), _c(9, 2),
            _c(3, 0), _c(3, 1), _c(4, 0), _c(4, 1)])
        assert play.type_id == PLANE_2


class TestIdentifySpecial:
    """炸弹/火箭/四带二"""

    def test_bomb(self):
        play = identify([_c(7, 0), _c(7, 1), _c(7, 2), _c(7, 3)])
        assert play.type_id == BOMB

    def test_rocket(self):
        play = identify([_c(15, -1), _c(16, -2)])
        assert play.type_id == ROCKET

    def test_four_with_two_singles(self):
        play = identify([_c(7, 0), _c(7, 1), _c(7, 2), _c(7, 3), _c(3, 0), _c(5, 0)])
        assert play.type_id == FOUR_2

    def test_four_with_two_pairs(self):
        play = identify([
            _c(7, 0), _c(7, 1), _c(7, 2), _c(7, 3),
            _c(3, 0), _c(3, 1), _c(5, 0), _c(5, 1)])
        assert play.type_id == FOUR_2


class TestBeats:
    """牌型比较"""

    def test_rocket_beats_bomb(self):
        rocket = identify([_c(15, -1), _c(16, -2)])
        bomb = identify([_c(14, 0), _c(14, 1), _c(14, 2), _c(14, 3)])
        assert rocket.beats(bomb)
        assert not bomb.beats(rocket)

    def test_bomb_beats_non_bomb(self):
        bomb = identify([_c(3, 0), _c(3, 1), _c(3, 2), _c(3, 3)])
        straight = identify(_hand(3, 4, 5, 6, 7))
        assert bomb.beats(straight)

    def test_same_type_higher_rank_wins(self):
        pair_high = identify([_c(10, 0), _c(10, 1)])
        pair_low = identify([_c(5, 0), _c(5, 1)])
        assert pair_high.beats(pair_low)
        assert not pair_low.beats(pair_high)

    def test_different_type_no_beat(self):
        single = identify(_hand(14))
        pair = identify([_c(3, 0), _c(3, 1)])
        assert not single.beats(pair)


class TestInvalidHands:
    """无效出牌"""

    def test_random_cards_invalid(self):
        assert identify(_hand(3, 5, 8)) is None

    def test_two_singles_invalid(self):
        assert identify(_hand(3, 5)) is None


class TestSortHand:
    """手牌排序"""

    def test_descending_order(self):
        hand = _hand(3, 14, 7, 2)
        sorted_h = sort_hand(hand)
        ranks = [doudizhu_rank(c) for c in sorted_h]
        assert ranks == sorted(ranks, reverse=True)

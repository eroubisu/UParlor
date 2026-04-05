"""德州扑克牌型评估测试"""

from __future__ import annotations

import pytest

from server.games.cards.deck import Card
from server.games.cards.hand_eval import (
    FLUSH, FOUR_OF_A_KIND, FULL_HOUSE, HIGH_CARD, ONE_PAIR,
    ROYAL_FLUSH, STRAIGHT, STRAIGHT_FLUSH, THREE_OF_A_KIND, TWO_PAIR,
    evaluate_hand,
)


def _cards(specs: list[tuple[int, int]]) -> list[Card]:
    """(rank, suit) 列表 → Card 列表"""
    return [Card(suit=s, rank=r) for r, s in specs]


class TestEvalFive:
    """精确 5 张牌型识别"""

    def test_royal_flush(self):
        hand = _cards([(14, 0), (13, 0), (12, 0), (11, 0), (10, 0)])
        rank, tb = evaluate_hand(hand)
        assert rank == ROYAL_FLUSH

    def test_straight_flush(self):
        hand = _cards([(9, 1), (8, 1), (7, 1), (6, 1), (5, 1)])
        rank, tb = evaluate_hand(hand)
        assert rank == STRAIGHT_FLUSH
        assert tb == (9,)

    def test_four_of_a_kind(self):
        hand = _cards([(7, 0), (7, 1), (7, 2), (7, 3), (2, 0)])
        rank, tb = evaluate_hand(hand)
        assert rank == FOUR_OF_A_KIND
        assert tb == (7, 2)

    def test_full_house(self):
        hand = _cards([(10, 0), (10, 1), (10, 2), (4, 0), (4, 1)])
        rank, tb = evaluate_hand(hand)
        assert rank == FULL_HOUSE
        assert tb == (10, 4)

    def test_flush(self):
        hand = _cards([(14, 2), (10, 2), (7, 2), (5, 2), (3, 2)])
        rank, tb = evaluate_hand(hand)
        assert rank == FLUSH
        assert tb == (14, 10, 7, 5, 3)

    def test_straight(self):
        hand = _cards([(8, 0), (7, 1), (6, 2), (5, 3), (4, 0)])
        rank, tb = evaluate_hand(hand)
        assert rank == STRAIGHT
        assert tb == (8,)

    def test_wheel_straight(self):
        """A-2-3-4-5 低顺"""
        hand = _cards([(14, 0), (2, 1), (3, 2), (4, 3), (5, 0)])
        rank, tb = evaluate_hand(hand)
        assert rank == STRAIGHT
        assert tb == (5,)  # 5-high

    def test_three_of_a_kind(self):
        hand = _cards([(9, 0), (9, 1), (9, 2), (13, 0), (2, 1)])
        rank, tb = evaluate_hand(hand)
        assert rank == THREE_OF_A_KIND
        assert tb[0] == 9  # trip rank

    def test_two_pair(self):
        hand = _cards([(11, 0), (11, 1), (5, 2), (5, 3), (14, 0)])
        rank, tb = evaluate_hand(hand)
        assert rank == TWO_PAIR
        assert tb == (11, 5, 14)

    def test_one_pair(self):
        hand = _cards([(8, 0), (8, 1), (14, 2), (12, 3), (3, 0)])
        rank, tb = evaluate_hand(hand)
        assert rank == ONE_PAIR
        assert tb == (8, 14, 12, 3)

    def test_high_card(self):
        hand = _cards([(14, 0), (10, 1), (7, 2), (5, 3), (2, 0)])
        rank, tb = evaluate_hand(hand)
        assert rank == HIGH_CARD
        assert tb == (14, 10, 7, 5, 2)


class TestBestOfSeven:
    """从 7 张牌中选最佳 5 张"""

    def test_seven_cards_picks_best(self):
        hand = _cards([
            (14, 0), (14, 1), (14, 2),  # 三条 A
            (13, 0), (13, 1),            # 一对 K
            (2, 0), (3, 1),
        ])
        rank, tb = evaluate_hand(hand)
        assert rank == FULL_HOUSE
        assert tb == (14, 13)

    def test_flush_hidden_in_seven(self):
        hand = _cards([
            (14, 0), (10, 0), (7, 0), (5, 0), (3, 0),  # ♠ flush
            (14, 1), (13, 2),
        ])
        rank, _ = evaluate_hand(hand)
        assert rank == FLUSH


class TestEdgeCases:
    """边界条件"""

    def test_less_than_five_returns_zero(self):
        hand = _cards([(14, 0), (13, 0)])
        rank, _ = evaluate_hand(hand)
        assert rank == 0

    def test_empty_hand(self):
        rank, _ = evaluate_hand([])
        assert rank == 0

    def test_comparison_order(self):
        """更高牌型 > 更低牌型"""
        flush = _cards([(14, 0), (10, 0), (7, 0), (5, 0), (3, 0)])
        straight = _cards([(8, 0), (7, 1), (6, 2), (5, 3), (4, 0)])
        assert evaluate_hand(flush) > evaluate_hand(straight)

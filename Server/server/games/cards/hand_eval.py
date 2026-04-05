"""德州扑克牌型评估"""

from __future__ import annotations

from collections import Counter
from .deck import Card

# 牌型等级 (越大越强)
ROYAL_FLUSH = 10
STRAIGHT_FLUSH = 9
FOUR_OF_A_KIND = 8
FULL_HOUSE = 7
FLUSH = 6
STRAIGHT = 5
THREE_OF_A_KIND = 4
TWO_PAIR = 3
ONE_PAIR = 2
HIGH_CARD = 1

HAND_NAMES = {
    ROYAL_FLUSH: '皇家同花顺',
    STRAIGHT_FLUSH: '同花顺',
    FOUR_OF_A_KIND: '四条',
    FULL_HOUSE: '葫芦',
    FLUSH: '同花',
    STRAIGHT: '顺子',
    THREE_OF_A_KIND: '三条',
    TWO_PAIR: '两对',
    ONE_PAIR: '一对',
    HIGH_CARD: '高牌',
}


def evaluate_hand(cards: list[Card]) -> tuple[int, tuple]:
    """从 5-7 张牌中评估最佳 5 张组合

    Returns: (hand_rank, tiebreaker_tuple)
        hand_rank: 1-10 (HIGH_CARD 到 ROYAL_FLUSH)
        tiebreaker: 用于同级别比较的元组（越大越强）
    """
    if len(cards) < 5:
        return (0, ())
    best = (0, ())
    from itertools import combinations
    for combo in combinations(cards, 5):
        val = _eval_five(list(combo))
        if val > best:
            best = val
    return best


def _eval_five(cards: list[Card]) -> tuple[int, tuple]:
    """评估精确 5 张的牌型"""
    ranks = sorted((c.rank for c in cards), reverse=True)
    suits = [c.suit for c in cards]
    rank_counts = Counter(ranks)
    is_flush = len(set(suits)) == 1

    # 顺子检测
    is_straight = False
    high = ranks[0]
    if ranks == list(range(high, high - 5, -1)):
        is_straight = True
    # A-2-3-4-5 (wheel)
    elif ranks == [14, 5, 4, 3, 2]:
        is_straight = True
        high = 5  # 5-high straight

    if is_straight and is_flush:
        if high == 14 and ranks[1] == 13:  # A-K-Q-J-10
            return (ROYAL_FLUSH, (high,))
        return (STRAIGHT_FLUSH, (high,))

    # 按频次降序分组
    groups = sorted(rank_counts.items(), key=lambda x: (x[1], x[0]), reverse=True)

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = groups[1][0]
        return (FOUR_OF_A_KIND, (quad, kicker))

    if groups[0][1] == 3 and groups[1][1] == 2:
        return (FULL_HOUSE, (groups[0][0], groups[1][0]))

    if is_flush:
        return (FLUSH, tuple(ranks))

    if is_straight:
        return (STRAIGHT, (high,))

    if groups[0][1] == 3:
        trip = groups[0][0]
        kickers = sorted([g[0] for g in groups[1:]], reverse=True)
        return (THREE_OF_A_KIND, (trip, *kickers))

    if groups[0][1] == 2 and groups[1][1] == 2:
        pairs = sorted([groups[0][0], groups[1][0]], reverse=True)
        kicker = groups[2][0]
        return (TWO_PAIR, (*pairs, kicker))

    if groups[0][1] == 2:
        pair = groups[0][0]
        kickers = sorted([g[0] for g in groups[1:]], reverse=True)
        return (ONE_PAIR, (pair, *kickers))

    return (HIGH_CARD, tuple(ranks))

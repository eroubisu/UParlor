"""扑克牌和牌组"""

from __future__ import annotations

import random
from dataclasses import dataclass

SUIT_SYMBOLS = ('♠', '♥', '♦', '♣')
RANK_NAMES = {
    2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8',
    9: '9', 10: '10', 11: 'J', 12: 'Q', 13: 'K', 14: 'A',
    15: 'S☆', 16: 'B☆',  # 小王/大王
}


@dataclass(frozen=True, slots=True)
class Card:
    """一张扑克牌

    suit: 0=♠ 1=♥ 2=♦ 3=♣ (-1=小王 -2=大王)
    rank: 2-14 (A=14), 15=小王, 16=大王
    """
    suit: int
    rank: int

    @property
    def name(self) -> str:
        if self.rank >= 15:
            return RANK_NAMES[self.rank]
        return f'{RANK_NAMES[self.rank]}{SUIT_SYMBOLS[self.suit]}'

    @property
    def short(self) -> str:
        """简短显示用于渲染: [A♠] 风格"""
        return f'[{self.name}]'

    @property
    def is_red(self) -> bool:
        return self.suit in (1, 2)

    def __repr__(self) -> str:
        return self.name


class Deck:
    """一副扑克牌"""

    def __init__(self, jokers: bool = False):
        self._cards: list[Card] = []
        for suit in range(4):
            for rank in range(2, 15):
                self._cards.append(Card(suit, rank))
        if jokers:
            self._cards.append(Card(-1, 15))  # 小王
            self._cards.append(Card(-2, 16))  # 大王

    def shuffle(self) -> None:
        random.shuffle(self._cards)

    def deal(self, n: int = 1) -> list[Card]:
        """发 n 张牌"""
        dealt = self._cards[:n]
        self._cards = self._cards[n:]
        return dealt

    def deal_one(self) -> Card | None:
        return self._cards.pop(0) if self._cards else None

    @property
    def remaining(self) -> int:
        return len(self._cards)

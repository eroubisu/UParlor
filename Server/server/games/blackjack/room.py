"""21点房间状态

流程: 下注 → 发牌 → 轮流操作(hit/stand/double) → 庄家补牌 → 结算
庄家为 NPC，≤16 补牌，≥17 停牌。
"""

from __future__ import annotations

from ..cards.deck import Card, Deck

# 点数计算
def hand_value(cards: list[Card]) -> tuple[int, bool]:
    """计算手牌点数，返回 (最优点数, is_soft)
    
    A 可以算 1 或 11（soft hand）。
    """
    total = 0
    aces = 0
    for c in cards:
        if c.rank == 14:  # Ace
            total += 11
            aces += 1
        elif c.rank >= 11:  # J Q K
            total += 10
        else:
            total += c.rank
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    soft = aces > 0 and total <= 21
    return total, soft


def is_blackjack(cards: list[Card]) -> bool:
    """天然 21 点（2 张 = 21）"""
    return len(cards) == 2 and hand_value(cards)[0] == 21


class PlayerHand:
    """一手牌（可能分牌后有多手）"""

    def __init__(self, bet: int):
        self.cards: list[Card] = []
        self.bet: int = bet
        self.stood: bool = False
        self.busted: bool = False
        self.doubled: bool = False

    @property
    def value(self) -> int:
        return hand_value(self.cards)[0]

    @property
    def is_soft(self) -> bool:
        return hand_value(self.cards)[1]

    @property
    def is_blackjack(self) -> bool:
        return is_blackjack(self.cards)


class BlackjackRoom:
    """21 点房间
    
    players: list[str | None]  最多 6 人
    庄家是 NPC (dealer)
    """

    MAX_PLAYERS = 6
    DEFAULT_BET = 100

    def __init__(self, room_id: str, host: str):
        self.room_id = room_id
        self.host = host
        self.state = 'waiting'  # waiting → betting → playing → dealer → finished
        self.players: list[str | None] = [host] + [None] * (self.MAX_PLAYERS - 1)
        self.deck: Deck = Deck()
        self.bots: set[str] = set()

        # 游戏中数据
        self.hands: dict[str, PlayerHand] = {}  # player_name → PlayerHand
        self.dealer_cards: list[Card] = []
        self.turn_order: list[str] = []  # 行动顺序
        self.current_turn: int = 0  # 当前行动者索引

    def _deal_one(self) -> Card:
        """安全发牌 — 牌不够时自动重洗"""
        if not self.deck._cards:
            self.deck = Deck()
            self.deck.shuffle()
        return self.deck.deal(1)[0]

    @property
    def player_count(self) -> int:
        return sum(1 for p in self.players if p)

    def is_full(self) -> bool:
        return self.player_count >= self.MAX_PLAYERS

    def add_player(self, name: str) -> bool:
        for i in range(self.MAX_PLAYERS):
            if self.players[i] is None:
                self.players[i] = name
                return True
        return False

    def remove_player(self, name: str):
        for i in range(self.MAX_PLAYERS):
            if self.players[i] == name:
                self.players[i] = None
        self.hands.pop(name, None)
        self.bots.discard(name)

    def active_players(self) -> list[str]:
        return [p for p in self.players if p]

    def is_bot(self, name: str) -> bool:
        return name in self.bots

    def add_bot(self) -> tuple[bool, str]:
        n = len(self.bots) + 1
        name = f'Bot_{n}'
        while name in self.bots:
            n += 1
            name = f'Bot_{n}'
        if self.add_player(name):
            self.bots.add(name)
            return True, name
        return False, ''

    def start(self):
        """开始发牌"""
        self.deck = Deck()
        self.deck.shuffle()
        self.hands.clear()
        self.dealer_cards.clear()

        active = self.active_players()
        for p in active:
            hand = PlayerHand(self.DEFAULT_BET)
            hand.cards.append(self._deal_one())
            self.hands[p] = hand

        self.dealer_cards.append(self._deal_one())

        for p in active:
            self.hands[p].cards.append(self._deal_one())

        self.dealer_cards.append(self._deal_one())  # 暗牌

        self.turn_order = active[:]
        self.current_turn = 0
        self.state = 'playing'

        # 跳过天然 21 点的玩家
        self._skip_blackjacks()

    def _skip_blackjacks(self):
        while self.current_turn < len(self.turn_order):
            name = self.turn_order[self.current_turn]
            hand = self.hands.get(name)
            if hand and hand.is_blackjack:
                hand.stood = True
                self.current_turn += 1
            else:
                break
        if self.current_turn >= len(self.turn_order):
            self._dealer_turn()

    def current_player(self) -> str | None:
        if self.state != 'playing':
            return None
        if self.current_turn < len(self.turn_order):
            return self.turn_order[self.current_turn]
        return None

    def hit(self, name: str) -> bool:
        """要牌"""
        hand = self.hands.get(name)
        if not hand or hand.stood or hand.busted:
            return False
        card = self._deal_one()
        hand.cards.append(card)
        if hand.value > 21:
            hand.busted = True
            self._advance_turn()
        return True

    def stand(self, name: str) -> bool:
        """停牌"""
        hand = self.hands.get(name)
        if not hand or hand.stood or hand.busted:
            return False
        hand.stood = True
        self._advance_turn()
        return True

    def double_down(self, name: str) -> bool:
        """加倍 — 只能在 2 张牌时"""
        hand = self.hands.get(name)
        if not hand or hand.stood or hand.busted:
            return False
        if len(hand.cards) != 2:
            return False
        hand.bet *= 2
        hand.doubled = True
        card = self._deal_one()
        hand.cards.append(card)
        if hand.value > 21:
            hand.busted = True
        hand.stood = True
        self._advance_turn()
        return True

    def _advance_turn(self):
        self.current_turn += 1
        while self.current_turn < len(self.turn_order):
            name = self.turn_order[self.current_turn]
            hand = self.hands.get(name)
            if hand and hand.is_blackjack:
                hand.stood = True
                self.current_turn += 1
            else:
                break
        if self.current_turn >= len(self.turn_order):
            self._dealer_turn()

    def _dealer_turn(self):
        """庄家补牌: ≤16补, ≥17停"""
        self.state = 'dealer'
        # 如果所有人都爆了，庄家不需要补牌
        all_busted = all(h.busted for h in self.hands.values())
        if not all_busted:
            while hand_value(self.dealer_cards)[0] < 17:
                self.dealer_cards.append(self._deal_one())
        self.state = 'finished'

    def get_results(self) -> dict[str, dict]:
        """计算每个玩家的结算"""
        dealer_val = hand_value(self.dealer_cards)[0]
        dealer_bj = is_blackjack(self.dealer_cards)
        dealer_bust = dealer_val > 21

        results = {}
        for name, hand in self.hands.items():
            pval = hand.value
            if hand.busted:
                outcome = 'lose'
                payout = -hand.bet
            elif hand.is_blackjack:
                if dealer_bj:
                    outcome = 'push'
                    payout = 0
                else:
                    outcome = 'blackjack'
                    payout = int(hand.bet * 1.5)
            elif dealer_bust:
                outcome = 'win'
                payout = hand.bet
            elif pval > dealer_val:
                outcome = 'win'
                payout = hand.bet
            elif pval == dealer_val:
                outcome = 'push'
                payout = 0
            else:
                outcome = 'lose'
                payout = -hand.bet

            results[name] = {
                'outcome': outcome,
                'payout': payout,
                'cards': [c.name for c in hand.cards],
                'value': pval,
                'bet': hand.bet,
            }
        return results

    def get_game_data(self, viewer: str | None = None) -> dict:
        """构建客户端渲染数据"""
        # 庄家手牌：playing 状态只显示第一张
        show_dealer = self.state in ('dealer', 'finished')
        dealer_display = []
        for i, c in enumerate(self.dealer_cards):
            if show_dealer or i == 0:
                dealer_display.append(c.name)
            else:
                dealer_display.append('??')

        dealer_val = hand_value(self.dealer_cards)[0] if show_dealer else None

        players_data = []
        for p in self.turn_order if self.turn_order else self.active_players():
            hand = self.hands.get(p)
            if not hand:
                continue
            is_current = (self.state == 'playing'
                          and self.current_turn < len(self.turn_order)
                          and self.turn_order[self.current_turn] == p)
            players_data.append({
                'name': p,
                'cards': [c.name for c in hand.cards],
                'value': hand.value,
                'bet': hand.bet,
                'stood': hand.stood,
                'busted': hand.busted,
                'doubled': hand.doubled,
                'is_blackjack': hand.is_blackjack,
                'is_current': is_current,
            })

        data = {
            'game_type': 'blackjack',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'players': [p for p in self.players if p],
            'dealer_cards': dealer_display,
            'dealer_value': dealer_val,
            'players_data': players_data,
            'current_player': self.current_player(),
        }

        if self.state == 'finished':
            data['results'] = self.get_results()

        return data

    def get_table_data(self) -> dict:
        return {
            'game_type': 'blackjack',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'players': [p for p in self.players if p],
            'player_count': self.player_count,
            'max_players': self.MAX_PLAYERS,
        }

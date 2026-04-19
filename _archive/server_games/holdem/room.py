"""德州扑克房间状态

流程: 小盲/大盲 → 发手牌(2张) → preflop下注 →
      翻牌(3张) → 下注 → 转牌(1张) → 下注 → 河牌(1张) → 最终下注 → 摊牌
"""

from __future__ import annotations

from ..cards.deck import Card, Deck
from ..cards.hand_eval import evaluate_hand as best_hand, HAND_NAMES

SMALL_BLIND = 50
BIG_BLIND = 100
STARTING_CHIPS = 10000


class PlayerSeat:
    """德州扑克座位"""

    def __init__(self, name: str, chips: int = STARTING_CHIPS):
        self.name = name
        self.chips = chips
        self.hand: list[Card] = []
        self.bet_this_round: int = 0
        self.total_bet: int = 0
        self.folded: bool = False
        self.all_in: bool = False
        self.active: bool = True  # 还在本局游戏中

    def reset_for_hand(self):
        self.hand.clear()
        self.bet_this_round = 0
        self.total_bet = 0
        self.folded = False
        self.all_in = False
        self.active = self.chips > 0


class HoldemRoom:
    """德州扑克房间 — 2-6人"""

    MAX_PLAYERS = 6

    def __init__(self, room_id: str, host: str):
        self.room_id = room_id
        self.host = host
        self.state = 'waiting'  # waiting → playing → showdown → finished
        self.seats: list[PlayerSeat | None] = [PlayerSeat(host)] + [None] * (self.MAX_PLAYERS - 1)
        self.deck: Deck = Deck()
        self.bots: set[str] = set()

        # 游戏状态
        self.community: list[Card] = []
        self.pot: int = 0
        self.side_pots: list[dict] = []  # [{amount, eligible: [names]}]
        self.current_bet: int = 0
        self.min_raise: int = BIG_BLIND

        self.dealer_idx: int = 0  # 庄家位置
        self.action_idx: int = 0  # 当前行动者
        self.phase: str = 'preflop'  # preflop/flop/turn/river/showdown
        self.last_raiser_idx: int = -1

        # 结算
        self.winners: list[dict] = []

    @property
    def player_count(self) -> int:
        return sum(1 for s in self.seats if s)

    def is_full(self) -> bool:
        return self.player_count >= self.MAX_PLAYERS

    def get_seat(self, name: str) -> PlayerSeat | None:
        for s in self.seats:
            if s and s.name == name:
                return s
        return None

    def get_seat_idx(self, name: str) -> int | None:
        for i, s in enumerate(self.seats):
            if s and s.name == name:
                return i
        return None

    def add_player(self, name: str) -> bool:
        for i in range(self.MAX_PLAYERS):
            if self.seats[i] is None:
                self.seats[i] = PlayerSeat(name)
                return True
        return False

    def remove_player(self, name: str):
        for i in range(self.MAX_PLAYERS):
            if self.seats[i] and self.seats[i].name == name:
                self.seats[i] = None
        self.bots.discard(name)

    def active_players(self) -> list[str]:
        return [s.name for s in self.seats if s]

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

    def _active_seats(self) -> list[tuple[int, PlayerSeat]]:
        return [(i, s) for i, s in enumerate(self.seats) if s]

    def _in_hand_seats(self) -> list[tuple[int, PlayerSeat]]:
        """还没弃牌且有筹码的座位"""
        return [(i, s) for i, s in enumerate(self.seats)
                if s and not s.folded and s.active]

    def _can_act_seats(self) -> list[tuple[int, PlayerSeat]]:
        """还能行动（没弃牌、没 all-in）"""
        return [(i, s) for i, s in enumerate(self.seats)
                if s and not s.folded and not s.all_in and s.active]

    # ── 开始新一手 ──

    def start_hand(self):
        self.deck = Deck()
        self.deck.shuffle()
        self.community.clear()
        self.pot = 0
        self.side_pots.clear()
        self.current_bet = 0
        self.min_raise = BIG_BLIND
        self.winners.clear()
        self.phase = 'preflop'
        self.state = 'playing'

        seats = self._active_seats()
        for _, s in seats:
            s.reset_for_hand()

        # 移动庄家
        self.dealer_idx = self._next_seat(self.dealer_idx)

        # 盲注
        n = len(seats)
        if n == 2:
            sb_idx = self.dealer_idx
            bb_idx = self._next_seat(sb_idx)
        else:
            sb_idx = self._next_seat(self.dealer_idx)
            bb_idx = self._next_seat(sb_idx)

        self._place_bet_idx(sb_idx, SMALL_BLIND)
        self._place_bet_idx(bb_idx, BIG_BLIND)
        self.current_bet = BIG_BLIND

        # 发手牌
        for _ in range(2):
            for _, s in seats:
                s.hand.append(self.deck.deal(1)[0])

        # 行动从大盲后一人开始
        self.action_idx = self._next_seat(bb_idx)
        self.last_raiser_idx = bb_idx

    def _next_seat(self, idx: int) -> int:
        """找到下一个有人的座位"""
        for offset in range(1, self.MAX_PLAYERS + 1):
            ni = (idx + offset) % self.MAX_PLAYERS
            if self.seats[ni]:
                return ni
        return idx

    def _next_active_seat(self, idx: int) -> int:
        """找到下一个还能行动的人"""
        for offset in range(1, self.MAX_PLAYERS + 1):
            ni = (idx + offset) % self.MAX_PLAYERS
            s = self.seats[ni]
            if s and not s.folded and not s.all_in and s.active:
                return ni
        return idx

    def _place_bet_idx(self, idx: int, amount: int):
        s = self.seats[idx]
        if not s:
            return
        actual = min(amount, s.chips)
        s.chips -= actual
        s.bet_this_round += actual
        s.total_bet += actual
        self.pot += actual
        if s.chips <= 0:
            s.all_in = True

    # ── 玩家操作 ──

    def current_player(self) -> str | None:
        if self.state != 'playing':
            return None
        s = self.seats[self.action_idx]
        if s and not s.folded and not s.all_in and s.active:
            return s.name
        return None

    def fold(self, name: str) -> bool:
        seat = self.get_seat(name)
        if not seat or seat.folded:
            return False
        seat.folded = True
        self._after_action()
        return True

    def call(self, name: str) -> bool:
        seat = self.get_seat(name)
        if not seat or seat.folded:
            return False
        to_call = self.current_bet - seat.bet_this_round
        if to_call <= 0:
            return False
        idx = self.get_seat_idx(name)
        self._place_bet_idx(idx, to_call)
        self._after_action()
        return True

    def check(self, name: str) -> bool:
        seat = self.get_seat(name)
        if not seat or seat.folded:
            return False
        if seat.bet_this_round < self.current_bet:
            return False  # 需要 call 不能 check
        self._after_action()
        return True

    def raise_bet(self, name: str, total: int) -> bool:
        """加注到 total (总下注额)"""
        seat = self.get_seat(name)
        if not seat or seat.folded:
            return False
        raise_amount = total - self.current_bet
        if raise_amount < self.min_raise and total < seat.chips + seat.bet_this_round:
            return False
        to_put = total - seat.bet_this_round
        if to_put <= 0:
            return False
        idx = self.get_seat_idx(name)
        self._place_bet_idx(idx, to_put)
        self.min_raise = max(self.min_raise, total - self.current_bet)
        self.current_bet = total
        self.last_raiser_idx = idx
        self._after_action()
        return True

    def all_in(self, name: str) -> bool:
        seat = self.get_seat(name)
        if not seat or seat.folded or seat.all_in:
            return False
        idx = self.get_seat_idx(name)
        total = seat.bet_this_round + seat.chips
        if total > self.current_bet:
            self.min_raise = max(self.min_raise, total - self.current_bet)
            self.current_bet = total
            self.last_raiser_idx = idx
        self._place_bet_idx(idx, seat.chips)
        self._after_action()
        return True

    def _after_action(self):
        """行动后检查是否结束当前轮次"""
        in_hand = self._in_hand_seats()
        if len(in_hand) <= 1:
            # 只剩一人，直接获胜
            self._resolve_winner()
            return

        can_act = self._can_act_seats()
        if not can_act:
            # 所有人都 all-in 或弃牌 → 直接翻完公共牌
            self._run_out()
            return

        # 移到下一个能行动的人
        next_idx = self._next_active_seat(self.action_idx)

        # 检查是否所有能行动的人下注一致且轮回完成
        all_equal = all(s.bet_this_round == self.current_bet for _, s in can_act)
        if all_equal and (next_idx == self.last_raiser_idx
                          or self._is_all_in_idx(self.last_raiser_idx)):
            self._next_phase()
            return

        self.action_idx = next_idx

    def _is_all_in_idx(self, idx: int) -> bool:
        """检查指定座位是否已 all-in"""
        if idx < 0 or idx >= len(self.seats):
            return False
        s = self.seats[idx]
        return s is not None and s.all_in

    def _next_phase(self):
        """进入下一轮"""
        # 收集下注到底池
        for _, s in self._active_seats():
            s.bet_this_round = 0
        self.current_bet = 0
        self.min_raise = BIG_BLIND

        if self.phase == 'preflop':
            self.phase = 'flop'
            self.community.extend(self.deck.deal(3))
        elif self.phase == 'flop':
            self.phase = 'turn'
            self.community.extend(self.deck.deal(1))
        elif self.phase == 'turn':
            self.phase = 'river'
            self.community.extend(self.deck.deal(1))
        elif self.phase == 'river':
            self._showdown()
            return

        # 重置行动位 — 从庄家后一人开始
        can_act = self._can_act_seats()
        if not can_act:
            self._run_out()
            return
        self.action_idx = self._next_active_seat(self.dealer_idx)
        self.last_raiser_idx = self.action_idx

    def _run_out(self):
        """所有人已行动完毕但公共牌未发完 → 发完并摊牌"""
        while len(self.community) < 5:
            if self.phase == 'preflop':
                self.phase = 'flop'
                self.community.extend(self.deck.deal(3))
            elif self.phase == 'flop':
                self.phase = 'turn'
                self.community.extend(self.deck.deal(1))
            elif self.phase == 'turn':
                self.phase = 'river'
                self.community.extend(self.deck.deal(1))
            else:
                break
        self._showdown()

    def _showdown(self):
        """摊牌 — 评估手牌，按边池分配"""
        self.phase = 'showdown'
        self.state = 'showdown'

        in_hand = self._in_hand_seats()
        if len(in_hand) <= 1:
            self._resolve_winner()
            return

        # 评估每个人的最佳手牌
        ranks = {}
        for idx, s in in_hand:
            all_cards = s.hand + self.community
            rank_val, tiebreaker = best_hand(all_cards)
            ranks[s.name] = (rank_val, tiebreaker, s)

        # 构建边池: 按 total_bet 从低到高分层
        bettors = sorted(
            [(s.total_bet, s) for s in self.seats if s and s.total_bet > 0],
            key=lambda x: x[0])

        pots: list[tuple[int, list[str]]] = []
        prev = 0
        for bet, _ in bettors:
            if bet <= prev:
                continue
            pot_amount = 0
            eligible = []
            for tb, s in bettors:
                pot_amount += min(tb, bet) - min(tb, prev)
                if tb >= bet and not s.folded:
                    eligible.append(s.name)
            if pot_amount > 0:
                if not eligible:
                    eligible = list(ranks.keys())
                pots.append((pot_amount, eligible))
            prev = bet

        # 分配每个底池
        winner_totals: dict[str, int] = {}
        for pot_amount, eligible in pots:
            valid = [n for n in eligible if n in ranks]
            if not valid:
                valid = list(ranks.keys())
            best_val = max(ranks[n][:2] for n in valid)
            pot_winners = [n for n in valid if ranks[n][:2] == best_val]
            share = pot_amount // len(pot_winners)
            remainder = pot_amount - share * len(pot_winners)
            for i, n in enumerate(pot_winners):
                winner_totals[n] = (winner_totals.get(n, 0)
                                    + share + (remainder if i == 0 else 0))

        self.winners = []
        for name, amount in winner_totals.items():
            seat = ranks[name][2]
            seat.chips += amount
            self.winners.append({
                'name': name,
                'amount': amount,
                'hand_rank': ranks[name][0],
                'hand_name': HAND_NAMES.get(ranks[name][0], '?'),
                'cards': [c.name for c in seat.hand],
            })

        self.pot = 0
        self.state = 'finished'

    def _resolve_winner(self):
        """只剩一人获胜"""
        in_hand = self._in_hand_seats()
        if in_hand:
            _, winner = in_hand[0]
            winner.chips += self.pot
            self.winners = [{
                'name': winner.name,
                'amount': self.pot,
                'hand_rank': 0,
                'hand_name': '其他人弃牌',
                'cards': [c.name for c in winner.hand],
            }]
        self.pot = 0
        self.state = 'finished'

    # ── 数据输出 ──

    def get_game_data(self, viewer: str | None = None) -> dict:
        show_all = self.state in ('showdown', 'finished')

        seats_data = []
        for i, s in enumerate(self.seats):
            if not s:
                continue
            # 手牌：只有自己或摊牌时可见
            if show_all and not s.folded:
                cards = [c.name for c in s.hand]
            elif viewer and s.name == viewer:
                cards = [c.name for c in s.hand]
            else:
                cards = ['??', '??'] if s.hand else []

            is_current = (self.state == 'playing'
                          and i == self.action_idx
                          and not s.folded and not s.all_in)
            seats_data.append({
                'name': s.name,
                'chips': s.chips,
                'bet': s.bet_this_round,
                'total_bet': s.total_bet,
                'cards': cards,
                'folded': s.folded,
                'all_in': s.all_in,
                'is_dealer': i == self.dealer_idx,
                'is_current': is_current,
            })

        data = {
            'game_type': 'holdem',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'players': self.active_players(),
            'community': [c.name for c in self.community],
            'pot': self.pot,
            'current_bet': self.current_bet,
            'phase': self.phase,
            'seats': seats_data,
            'current_player': self.current_player(),
        }

        if viewer:
            seat = self.get_seat(viewer)
            if seat:
                to_call = max(0, self.current_bet - seat.bet_this_round)
                data['to_call'] = to_call
                data['can_check'] = to_call == 0
                data['min_raise'] = self.current_bet + self.min_raise
                data['viewer_chips'] = seat.chips

        if self.state == 'finished':
            data['winners'] = self.winners

        return data

    def get_table_data(self) -> dict:
        return {
            'game_type': 'holdem',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'players': self.active_players(),
            'player_count': self.player_count,
            'max_players': self.MAX_PLAYERS,
        }

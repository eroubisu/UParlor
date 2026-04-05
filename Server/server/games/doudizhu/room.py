"""斗地主房间逻辑 — 3 人，54 张牌

流程:
  1. 等待 3 人 → start()
  2. 发牌: 每人 17 张，留 3 张底牌
  3. 叫地主: 轮流叫分 (1/2/3)，最高者成为地主，获得底牌
  4. 出牌: 地主先出，逆时针轮转
  5. 某玩家出完手牌即胜
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..cards.deck import Card, Deck
from .patterns import (
    Play, identify, sort_hand, doudizhu_rank, PASS,
    BOMB, ROCKET, TYPE_NAMES,
)


@dataclass
class PlayerHand:
    name: str
    cards: list[Card] = field(default_factory=list)
    bid: int = 0       # 叫分 (0=不叫, 1/2/3)
    bid_done: bool = False


class DoudizhuRoom:
    """斗地主房间"""

    PLAYERS_NEEDED = 3

    def __init__(self, room_id: str, players: list[str]):
        self.room_id = room_id
        self.host = players[0]
        self.players = list(players)
        self.state = 'waiting'  # waiting → bidding → playing → finished
        self.bots: set[str] = set()

        self.hands: dict[str, PlayerHand] = {}
        self.dizhu_cards: list[Card] = []  # 底牌
        self.dizhu: str = ''               # 地主玩家名
        self.current_turn: int = 0         # 当前轮到的座位索引
        self.bid_round: int = 0            # 叫分轮次

        self.last_play: Play | None = None
        self.last_player: str = ''
        self.pass_count: int = 0           # 连续 pass 次数
        self.play_history: list[dict] = [] # 出牌记录
        self.play_round: int = 0           # 当前出牌轮次

        self.multiplier: int = 1           # 倍率 (炸弹/火箭翻倍)
        self.winner: str = ''
        self.spring: bool = False          # 春天

    def is_bot(self, name: str) -> bool:
        return name in self.bots

    def add_bot(self) -> tuple[bool, str]:
        if len(self.players) >= self.PLAYERS_NEEDED:
            return False, ''
        n = len(self.bots) + 1
        name = f'Bot_{n}'
        while name in self.bots:
            n += 1
            name = f'Bot_{n}'
        self.players.append(name)
        self.bots.add(name)
        self.hands[name] = None
        return True, name

    def is_full(self) -> bool:
        return len(self.players) >= self.PLAYERS_NEEDED

    def start(self) -> None:
        """发牌 + 进入叫分阶段"""
        deck = Deck(jokers=True)
        deck.shuffle()

        self.hands = {}
        for i, name in enumerate(self.players):
            cards = deck.deal(17)
            self.hands[name] = PlayerHand(name=name, cards=sort_hand(cards))

        self.dizhu_cards = sort_hand(deck.deal(3))
        self.state = 'bidding'
        self.current_turn = 0
        self.bid_round = 0
        self.multiplier = 1
        self.play_history = []
        self.play_round = 0

    def current_player(self) -> str:
        return self.players[self.current_turn]

    def bid(self, player: str, score: int) -> str | None:
        """叫分: 0=不叫, 1/2/3

        返回消息或 None (游戏继续)。
        如果叫 3 分直接成为地主。
        """
        if self.state != 'bidding':
            return None
        if player != self.current_player():
            return None

        hand = self.hands[player]
        if hand.bid_done:
            return None

        hand.bid = score
        hand.bid_done = True
        self.bid_round += 1

        # 叫3分直接成为地主
        if score == 3:
            self._set_dizhu(player, score)
            return self._bid_summary()

        # 所有人都叫完
        if self.bid_round >= 3:
            self._resolve_bidding()
            if self.state == 'bidding':
                # 无人叫分，已重新发牌
                return '无人叫分，重新发牌！'
            return self._bid_summary()

        # 下一位
        self._advance_turn()
        return f'{player} 叫了 {score} 分' if score > 0 else f'{player} 不叫'

    def _bid_summary(self) -> str:
        """生成完整叫分摘要"""
        lines = []
        for name in self.players:
            h = self.hands[name]
            if h.bid > 0:
                lines.append(f'{name} {h.bid}分')
            else:
                lines.append(f'{name} 不叫')
        lines.append(f'{self.dizhu} 成为地主')
        return '\n'.join(lines)

    def _resolve_bidding(self) -> None:
        """叫分结束，确定地主"""
        best_player = ''
        best_score = 0
        for name in self.players:
            h = self.hands[name]
            if h.bid > best_score:
                best_score = h.bid
                best_player = name

        if best_score == 0:
            # 无人叫分，重新发牌
            self.start()
            return

        self._set_dizhu(best_player, best_score)

    def _set_dizhu(self, player: str, score: int) -> None:
        """设定地主"""
        self.dizhu = player
        self.multiplier = score
        # 地主获得底牌
        self.hands[player].cards.extend(self.dizhu_cards)
        self.hands[player].cards = sort_hand(self.hands[player].cards)
        # 地主先出
        self.current_turn = self.players.index(player)
        self.state = 'playing'
        self.last_play = None
        self.last_player = ''
        self.pass_count = 0

    def play_cards(self, player: str, card_indices: list[int]) -> tuple[bool, str]:
        """出牌

        card_indices: 手牌中选中牌的索引列表 (0-based)
        返回 (success, message)
        """
        if self.state != 'playing':
            return False, '当前不在出牌阶段'
        if player != self.current_player():
            return False, '不是你的回合'

        hand = self.hands[player]

        # 没选任何牌 = pass
        if not card_indices:
            return self._do_pass(player)

        # 取出选中的牌
        indices = sorted(card_indices)
        if len(indices) != len(set(indices)):
            return False, '牌序号不能重复'
        if any(i < 0 or i >= len(hand.cards) for i in indices):
            return False, '无效的牌索引'

        selected = [hand.cards[i] for i in indices]
        play = identify(selected)
        if play is None:
            return False, '无效的牌型'

        # 如果场上有牌，必须压过
        if self.last_play and self.last_play.type_id != PASS:
            if not play.beats(self.last_play):
                return False, '出的牌必须大于上一手'

        # 出牌成功：从手牌移除
        for i in sorted(indices, reverse=True):
            hand.cards.pop(i)

        if not self.last_play:
            self.play_round += 1
        self.last_play = play
        self.last_player = player
        self.pass_count = 0
        self.play_history.append({
            'player': player,
            'type': play.name,
            'cards': [c.name for c in play.cards],
            'round': self.play_round,
        })

        # 炸弹/火箭翻倍（上限 64 倍）
        if play.type_id in (BOMB, ROCKET):
            self.multiplier = min(self.multiplier * 2, 64)

        # 检查胜利
        if not hand.cards:
            self._finish(player)
            return True, f'{player} 出完了所有牌！'

        self._advance_turn()
        return True, f'{player} 出了 {play.name}'

    def _do_pass(self, player: str) -> tuple[bool, str]:
        """玩家选择不出"""
        # 第一个出牌的人不能 pass (新一轮)
        if not self.last_play or self.last_player == player:
            return False, '你是第一个出牌，必须出牌'

        self.pass_count += 1

        # 两人都 pass，本轮结束，出牌者获得新一轮
        if self.pass_count >= 2:
            winner_idx = self.players.index(self.last_player)
            self.last_play = None
            self.last_player = ''
            self.pass_count = 0
            self.current_turn = winner_idx
            return True, f'{player} 不出'

        self._advance_turn()
        return True, f'{player} 不出'

    def _advance_turn(self) -> None:
        self.current_turn = (self.current_turn + 1) % 3

    def _finish(self, winner: str) -> None:
        self.winner = winner
        self.state = 'finished'

        # 判断春天: 地主赢 + 两农民一张没出 / 农民赢 + 地主只出了一手
        if winner == self.dizhu:
            farmers = [n for n in self.players if n != self.dizhu]
            if all(len(self.hands[f].cards) == 17 for f in farmers):
                self.spring = True
                self.multiplier *= 2
        else:
            if len(self.hands[self.dizhu].cards) == 20:  # 20=17+3底牌
                self.spring = True
                self.multiplier *= 2

    def get_results(self) -> dict[str, str]:
        """返回 {player_name: 'win'|'loss'}"""
        if not self.winner:
            return {}
        results = {}
        dizhu_won = self.winner == self.dizhu
        for name in self.players:
            if name == self.dizhu:
                results[name] = 'win' if dizhu_won else 'loss'
            else:
                results[name] = 'loss' if dizhu_won else 'win'
        return results

    def get_game_data(self, viewer: str) -> dict:
        """返回游戏状态供客户端渲染"""
        data: dict = {
            'game_type': 'doudizhu',
            'room_id': self.room_id,
            'room_state': self.state,
            'players': self.players,
            'dizhu': self.dizhu,
            'multiplier': self.multiplier,
            'current_player': self.current_player(),
        }

        if self.state == 'waiting':
            data['host'] = self.host
            data['max_players'] = self.PLAYERS_NEEDED
            return data

        if self.state == 'bidding':
            data['bids'] = {
                name: h.bid if h.bid_done else None
                for name, h in self.hands.items()
            }
            if viewer in self.hands:
                data['my_cards'] = [c.name for c in self.hands[viewer].cards]
            return data

        # playing / finished
        # 自己的手牌 (全部可见)
        if viewer in self.hands:
            data['my_cards'] = [c.name for c in self.hands[viewer].cards]
        else:
            data['my_cards'] = []

        # 其他人的手牌数量
        data['hand_counts'] = {
            name: len(h.cards) for name, h in self.hands.items()
        }

        # 底牌 (叫完地主后公开)
        data['dizhu_cards'] = [c.name for c in self.dizhu_cards]

        # 出牌记录
        data['play_history'] = self.play_history

        # 上一手牌
        if self.last_play and self.last_play.type_id != PASS:
            data['last_play'] = {
                'player': self.last_player,
                'type': self.last_play.name,
                'cards': [c.name for c in self.last_play.cards],
            }
        else:
            data['last_play'] = None

        # 结果
        if self.state == 'finished':
            data['winner'] = self.winner
            data['spring'] = self.spring
            data['results'] = self.get_results()

        # 推荐出牌 (viewer 是当前出牌者且需要接牌)
        elif (self.state == 'playing'
              and viewer == self.current_player()
              and self.last_play
              and self.last_play.type_id != PASS):
            from .patterns import find_all_beats
            hand = self.hands[viewer].cards
            data['suggestions'] = find_all_beats(hand, self.last_play)

        return data

    def get_table_data(self) -> dict:
        """供大厅列表显示"""
        return {
            'game_type': 'doudizhu',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'players': self.players,
            'player_count': len(self.players),
            'max_players': self.PLAYERS_NEEDED,
        }

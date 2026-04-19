"""UNO Flip 房间逻辑 — 2-10 人

流程:
  1. 等待 2-10 人 → start()
  2. 发牌 7 张，翻出首张到弃牌堆，Light Side 开始
  3. 出牌: 匹配颜色/数字/功能，或打 Wild
  4. Flip: 所有牌翻面，切换 Light↔Dark
  5. 某玩家出完手牌即胜，按剩余手牌计分

特殊规则:
  - 2 人: Reverse = Skip, Skip 给出牌者额外回合
  - Draw 类牌允许叠加（房规）
  - Wild Draw Two / Wild Draw Color 可被挑战
  - 剩 1 张时必须喊 UNO，否则被抓罚摸 2 张
"""

from __future__ import annotations

from .cards import (
    UnoCard, UnoDeck, can_play,
    LIGHT_COLORS, DARK_COLORS, COLOR_NAMES,
)


MIN_PLAYERS = 2
MAX_PLAYERS = 10


class UnoRoom:
    """UNO Flip 房间"""

    def __init__(self, room_id: str, players: list[str],
                 settings: dict | None = None):
        self.room_id = room_id
        self.host = players[0]
        self.players = list(players)
        self.state = 'waiting'  # waiting → playing → finished
        self.bots: set[str] = set()

        # 房间设置
        s = settings or {}
        self.max_players: int = s.get('max_players', MAX_PLAYERS)
        self.draw_stacking: bool = s.get('draw_stacking', True)
        self.challenge_enabled: bool = s.get('challenge', True)
        self.ranked: bool = s.get('mode', 'casual') == 'ranked'
        self.rank_tier: int = 0  # 竞技模式：房主段位阶梯

        # 游戏状态
        self.deck: UnoDeck | None = None
        self.hands: dict[str, list[UnoCard]] = {}
        self.discard_pile: list[UnoCard] = []  # [-1] 是顶牌
        self.side: str = 'light'  # 当前活跃面
        self.direction: int = 1   # +1=顺时针, -1=逆时针
        self.current_idx: int = 0
        self.chosen_color: str | None = None  # Wild 指定的颜色

        # Draw 叠加
        self.pending_draw: int = 0          # 累积摸牌数
        self.pending_draw_type: str = ''    # 'draw1'/'draw5'/'wild_draw2'
        # Wild Draw Color 特殊: 不用 pending_draw，而是摸到指定颜色为止
        self.draw_until_color: str | None = None

        # 挑战
        self.challengeable: bool = False     # 上一张是可被挑战的 Wild
        self.last_wild_player: str = ''      # 打出 Wild Draw 的玩家
        self.last_wild_had_match: bool = False  # 该玩家当时是否有匹配色牌

        # UNO 喊牌
        self.uno_called: set[str] = set()   # 已喊 UNO 的玩家

        # 摸牌后可出
        self.draw_play_card: int | None = None  # 摸到的可出牌索引

        # 结果
        self.winner: str = ''
        self.scores: dict[str, int] = {}
        self._result_pending: set[str] = set()  # 尚未确认结算的玩家

    def is_bot(self, name: str) -> bool:
        return name in self.bots

    def add_bot(self) -> tuple[bool, str]:
        if len(self.players) >= self.max_players:
            return False, ''
        n = len(self.bots) + 1
        name = f'Bot_{n}'
        while name in self.bots:
            n += 1
            name = f'Bot_{n}'
        self.players.append(name)
        self.bots.add(name)
        return True, name

    def is_full(self) -> bool:
        return len(self.players) >= self.max_players

    # ── 游戏开始 ──

    def start(self) -> str | None:
        """发牌并开始游戏。返回首张牌的消息（如果是功能牌）。"""
        import random as _rng
        _rng.shuffle(self.players)
        self.deck = UnoDeck()
        self.deck.shuffle()
        self.side = 'light'
        self.direction = 1
        self.current_idx = 0
        self.pending_draw = 0
        self.pending_draw_type = ''
        self.draw_until_color = None
        self.challengeable = False
        self.draw_play_card = None
        self.uno_called.clear()
        self.discard_pile.clear()
        self.hands.clear()

        # 发牌 7 张
        for name in self.players:
            self.hands[name] = self.deck.draw(7)

        # 翻出首张到弃牌堆
        first = self.deck.draw_one()
        # 如果首张是 Wild，放回重抽（官方规则）
        retries = 0
        while first and first.value in ('wild_draw2', 'wild_draw_color') and retries < 10:
            self.deck.put_bottom([first])
            self.deck.shuffle()
            first = self.deck.draw_one()
            retries += 1

        if first:
            self.discard_pile.append(first)

        self.state = 'playing'
        msg = None

        # 处理首张功能牌效果
        if first and not first.value.isdigit() and not first.is_wild:
            msg = self._apply_first_card_effect(first)
        elif first and first.is_wild and first.value == 'wild':
            # 首张 Wild: 第一个玩家选颜色（先设为 None，引擎处理）
            self.chosen_color = None

        return msg

    def _apply_first_card_effect(self, card: UnoCard) -> str:
        """处理首张翻出的功能牌效果"""
        v = card.value
        if v in ('skip', 'skip_all'):
            # 跳过第一个玩家
            self._advance_turn()
            return f'首张是 {card.label}，跳过第一位玩家。'
        if v == 'reverse':
            self.direction = -1
            if len(self.players) == 2:
                # 2 人时 Reverse = Skip
                self._advance_turn()
            return f'首张是 {card.label}，方向反转。'
        if v in ('draw1', 'draw5'):
            draw_n = 1 if v == 'draw1' else 5
            self.pending_draw = draw_n
            self.pending_draw_type = v
            return f'首张是 {card.label}，第一位玩家需摸 {draw_n} 张。'
        if v == 'flip':
            self._do_flip()
            return '首张是翻转牌，所有牌翻面！'
        return ''

    # ── 当前玩家 ──

    def current_player(self) -> str:
        return self.players[self.current_idx]

    def _advance_turn(self) -> None:
        self.current_idx = (self.current_idx + self.direction) % len(self.players)

    # ── 出牌 ──

    def get_playable_indices(self, player: str) -> list[int]:
        """返回玩家手牌中可出的牌索引列表"""
        hand = self.hands.get(player, [])
        top = self.discard_pile[-1] if self.discard_pile else None
        if not top:
            return list(range(len(hand)))

        # 摸牌后可出状态：只能出摸到的那张牌
        if self.draw_play_card is not None:
            idx = self.draw_play_card
            if idx < len(hand):
                return [idx]
            return []

        # 有 pending_draw 时只能出同类 Draw 牌叠加（需开启 draw_stacking）
        if self.pending_draw > 0 and self.pending_draw_type:
            if self.draw_stacking:
                return [i for i, c in enumerate(hand) if c.value == self.pending_draw_type]
            return []  # 不允许叠加，必须摸牌

        # Draw until color 时不能出牌（必须摸）
        if self.draw_until_color:
            return []

        return [i for i, c in enumerate(hand) if can_play(c, top, self.chosen_color)]

    def play_card(self, player: str, card_idx: int,
                  chosen_color: str | None = None) -> tuple[bool, str]:
        """出牌

        Returns: (success, message)
        """
        if self.state != 'playing':
            return False, '游戏未在进行中'
        if player != self.current_player():
            return False, '不是你的回合'

        hand = self.hands[player]
        if card_idx < 0 or card_idx >= len(hand):
            return False, '无效的牌索引'

        card = hand[card_idx]
        playable = self.get_playable_indices(player)
        if card_idx not in playable:
            return False, '这张牌不能打'

        # Wild 牌需要选颜色
        if card.is_wild and not chosen_color:
            return False, 'need_color'

        # 验证选色合法
        valid_colors = LIGHT_COLORS if self.side == 'light' else DARK_COLORS
        if chosen_color and chosen_color not in valid_colors:
            return False, '无效的颜色'

        # 记录挑战信息（Wild Draw 类）
        self.challengeable = False
        if self.challenge_enabled and card.value in ('wild_draw2', 'wild_draw_color'):
            top = self.discard_pile[-1] if self.discard_pile else None
            eff_color = self.chosen_color or (top.color if top else None)
            # 检查出牌者是否有匹配色的非 Wild 牌
            has_match = any(
                not c.is_wild and c.color == eff_color
                for i, c in enumerate(hand) if i != card_idx
            )
            self.challengeable = True
            self.last_wild_player = player
            self.last_wild_had_match = has_match

        # 出牌
        self.draw_play_card = None
        hand.pop(card_idx)
        self.discard_pile.append(card)
        self.chosen_color = chosen_color if card.is_wild else None

        # UNO 检查: 剩 1 张时需要喊 UNO（由引擎层处理 /uno 指令）
        # 出牌后移除之前的 UNO 状态
        self.uno_called.discard(player)

        # 检查是否赢了
        if not hand:
            return self._handle_win(player)

        # 应用功能牌效果
        card_label = card.label  # flip 会翻转牌面，先保存当前面 label
        effect_msg = self._apply_card_effect(card, player)

        return True, f'{player} 打出 {card_label}' + (f'，{effect_msg}' if effect_msg else '')

    def _apply_card_effect(self, card: UnoCard, player: str) -> str:
        """应用功能牌效果并轮转。返回效果描述。"""
        v = card.value
        is_two_player = len(self.players) == 2

        if v.isdigit():
            self._advance_turn()
            return ''

        if v == 'skip':
            if is_two_player:
                # 2 人: Skip = 额外回合（不轮转）
                return '跳过对方！'
            self._advance_turn()  # 跳过下家
            self._advance_turn()
            return f'跳过 {self.players[(self.current_idx - self.direction) % len(self.players)]}！'

        if v == 'skip_all':
            # 跳过所有人，出牌者再出
            return '跳过所有人！'

        if v == 'reverse':
            self.direction *= -1
            if is_two_player:
                # 2 人: Reverse = Skip
                return '反转（跳过对方）！'
            self._advance_turn()
            return '方向反转！'

        if v in ('draw1', 'draw5'):
            draw_n = 1 if v == 'draw1' else 5
            self.pending_draw += draw_n
            self.pending_draw_type = v
            self._advance_turn()
            return f'下家需摸 {self.pending_draw} 张（或叠加）！'

        if v == 'wild_draw2':
            self.pending_draw += 2
            self.pending_draw_type = 'wild_draw2'
            self._advance_turn()
            return f'下家需摸 {self.pending_draw} 张（可挑战/叠加）！'

        if v == 'wild_draw_color':
            # 下家持续摸牌直到摸到指定颜色
            self.draw_until_color = self.chosen_color
            self._advance_turn()
            return f'下家需摸牌直到获得{COLOR_NAMES.get(self.chosen_color, "?")}色（可挑战）！'

        if v == 'wild':
            self._advance_turn()
            c = COLOR_NAMES.get(self.chosen_color, '?')
            return f'指定颜色为{c}！'

        if v == 'flip':
            self._do_flip()
            self._advance_turn()
            return '所有牌翻面！'

        self._advance_turn()
        return ''

    def _do_flip(self) -> None:
        """翻转所有牌的面"""
        new_side = 'dark' if self.side == 'light' else 'light'
        self.side = new_side

        # 翻转牌堆
        self.deck.flip_all()

        # 翻转所有手牌
        for hand in self.hands.values():
            for card in hand:
                card.flip()

        # 翻转弃牌堆（Flip 牌本身移到底部，新顶牌是下一张）
        for card in self.discard_pile:
            card.flip()
        if len(self.discard_pile) > 1:
            # Flip 牌移到底部
            flip_card = self.discard_pile.pop()
            self.discard_pile.insert(0, flip_card)

        # 清除 Wild 指定色（翻面后颜色体系变了）
        self.chosen_color = None
        # 清除 pending draw（翻面后重置）
        self.pending_draw = 0
        self.pending_draw_type = ''
        self.draw_until_color = None
        self.challengeable = False

    # ── 摸牌 ──

    def draw_cards(self, player: str) -> tuple[bool, str, list[UnoCard]]:
        """摸牌

        Returns: (success, message, drawn_cards)
        """
        if self.state != 'playing':
            return False, '游戏未在进行中', []
        if player != self.current_player():
            return False, '不是你的回合', []

        drawn: list[UnoCard] = []

        if self.draw_until_color:
            # Wild Draw Color: 摸到指定颜色为止
            target_color = self.draw_until_color
            self.draw_until_color = None
            self.challengeable = False
            count = 0
            while True:
                card = self._safe_draw_one()
                if not card:
                    break
                self.hands[player].append(card)
                drawn.append(card)
                count += 1
                if card.color == target_color:
                    break
            self._advance_turn()
            return True, f'{player} 摸了 {count} 张牌（直到获得{COLOR_NAMES.get(target_color, "?")}色）', drawn

        if self.pending_draw > 0:
            # 累积 Draw: 摸指定数量
            n = self.pending_draw
            self.pending_draw = 0
            self.pending_draw_type = ''
            self.challengeable = False
            for _ in range(n):
                card = self._safe_draw_one()
                if not card:
                    break
                self.hands[player].append(card)
                drawn.append(card)
            self._advance_turn()
            return True, f'{player} 摸了 {len(drawn)} 张牌', drawn

        # 普通摸牌: 摸 1 张
        card = self._safe_draw_one()
        if not card:
            self._advance_turn()
            return True, f'{player} 牌堆已空', []
        self.hands[player].append(card)
        drawn.append(card)
        # 摸到的牌如果能打，可以选择打出或跳过
        top = self.discard_pile[-1] if self.discard_pile else None
        if top and can_play(card, top, self.chosen_color):
            self.draw_play_card = len(self.hands[player]) - 1
            return True, f'{player} 摸了 1 张牌', drawn
        self._advance_turn()
        return True, f'{player} 摸了 1 张牌', drawn

    def _safe_draw_one(self) -> UnoCard | None:
        """安全摸一张，牌堆空时从弃牌堆 reshuffle"""
        if self.deck.remaining == 0:
            self.deck.reshuffle_from(self.discard_pile)
        return self.deck.draw_one()

    # ── 挑战 ──

    def challenge(self, player: str) -> tuple[bool, str]:
        """挑战上家的 Wild Draw Two / Wild Draw Color

        Returns: (success, message)
        """
        if not self.challenge_enabled:
            return False, '本局未启用挑战规则'
        if not self.challengeable:
            return False, '当前没有可挑战的出牌'
        if player != self.current_player():
            return False, '不是你的回合'

        self.challengeable = False
        challenger = player
        offender = self.last_wild_player

        if self.last_wild_had_match:
            # 挑战成功: 出牌者违规，出牌者承担惩罚
            return self._challenge_success(challenger, offender)
        else:
            # 挑战失败: 挑战者加罚
            return self._challenge_fail(challenger, offender)

    def _challenge_success(self, challenger: str, offender: str) -> tuple[bool, str]:
        """挑战成功 — 出牌者违规"""
        top = self.discard_pile[-1] if self.discard_pile else None
        if not top:
            return False, '无效状态'

        if top.value == 'wild_draw2':
            # 出牌者摸 2 张
            n = self.pending_draw or 2
            self.pending_draw = 0
            self.pending_draw_type = ''
            for _ in range(n):
                card = self._safe_draw_one()
                if card:
                    self.hands[offender].append(card)
            return True, f'挑战成功！{offender} 违规出牌，摸 {n} 张。'

        if top.value == 'wild_draw_color':
            # 出牌者摸到指定颜色
            target = self.draw_until_color or self.chosen_color
            self.draw_until_color = None
            count = 0
            if target:
                while True:
                    card = self._safe_draw_one()
                    if not card:
                        break
                    self.hands[offender].append(card)
                    count += 1
                    if card.color == target:
                        break
            return True, f'挑战成功！{offender} 违规出牌，摸了 {count} 张。'

        return False, '无效状态'

    def _challenge_fail(self, challenger: str, offender: str) -> tuple[bool, str]:
        """挑战失败 — 挑战者加罚"""
        top = self.discard_pile[-1] if self.discard_pile else None
        if not top:
            return False, '无效状态'

        if top.value == 'wild_draw2':
            # 挑战者摸 pending + 2 额外
            n = (self.pending_draw or 2) + 2
            self.pending_draw = 0
            self.pending_draw_type = ''
            for _ in range(n):
                card = self._safe_draw_one()
                if card:
                    self.hands[challenger].append(card)
            self._advance_turn()
            return True, f'挑战失败！{challenger} 摸 {n} 张（含罚牌）。'

        if top.value == 'wild_draw_color':
            # 挑战者摸到指定颜色 + 额外 2 张
            target = self.draw_until_color or self.chosen_color
            self.draw_until_color = None
            count = 0
            if target:
                while True:
                    card = self._safe_draw_one()
                    if not card:
                        break
                    self.hands[challenger].append(card)
                    count += 1
                    if card.color == target:
                        break
            # 额外 2 张
            for _ in range(2):
                card = self._safe_draw_one()
                if card:
                    self.hands[challenger].append(card)
                    count += 1
            self._advance_turn()
            return True, f'挑战失败！{challenger} 摸了 {count} 张（含罚牌）。'

        return False, '无效状态'

    # ── UNO 喊牌 ──

    def call_uno(self, player: str) -> tuple[bool, str]:
        """喊 UNO"""
        hand = self.hands.get(player, [])
        if len(hand) != 1:
            return False, '只有剩 1 张牌时才能喊 UNO'
        self.uno_called.add(player)
        return True, f'{player} 喊了 UNO！'

    def pass_turn(self, player: str) -> tuple[bool, str]:
        """摸牌后放弃出牌"""
        if self.draw_play_card is None:
            return False, '当前不能跳过'
        if player != self.current_player():
            return False, '不是你的回合'
        self.draw_play_card = None
        self._advance_turn()
        return True, f'{player} 选择不出牌'

    # ── 获胜 ──

    def _handle_win(self, player: str) -> tuple[bool, str]:
        """处理赢家"""
        self.state = 'finished'
        self.winner = player

        # 计分: 赢家获得所有对手手牌的点数（按当前面）
        total = 0
        for name, hand in self.hands.items():
            if name == player:
                continue
            pts = sum(c.points for c in hand)
            self.scores[name] = pts
            total += pts
        self.scores[player] = total

        return True, f'{player} 出完了所有牌！获胜！得 {total} 分。'

    # ── 数据导出 ──

    def get_game_data(self, viewer: str) -> dict:
        """获取游戏数据（viewer 视角）"""
        top = self.discard_pile[-1] if self.discard_pile else None
        hand_counts = {p: len(h) for p, h in self.hands.items()}

        # 可出的牌
        playable = self.get_playable_indices(viewer) if viewer in self.hands else []

        # 已出过的颜色（从弃牌堆提取，排除 wild）
        side = self.side
        if side == 'light':
            color_order = [c for c in LIGHT_COLORS if c != 'wild']
        else:
            color_order = [c for c in DARK_COLORS if c != 'wild']
        seen = {c.color for c in self.discard_pile if not c.is_wild}
        played_colors = [c for c in color_order if c in seen]

        data = {
            'game_type': 'uno',
            'room_id': self.room_id,
            'room_state': self.state,
            'players': self.players,
            'host': self.host,
            'side': self.side,
            'direction': self.direction,
            'current_player': self.current_player() if self.state == 'playing' else '',
            'hand_counts': hand_counts,
            'chosen_color': self.chosen_color,
            'pending_draw': self.pending_draw,
            'draw_stacking': self.draw_stacking,
            'draw_until_color': self.draw_until_color,
            'challengeable': self.challengeable,
            'deck_remaining': self.deck.remaining if self.deck else 0,
            'uno_called': list(self.uno_called),
            'max_players': self.max_players,
            'played_colors': played_colors,
        }
        if top:
            data['top_card'] = top.to_dict()

        # 只给 viewer 看自己的手牌
        if viewer in self.hands:
            data['my_cards'] = [c.to_dict() for c in self.hands[viewer]]
            data['playable'] = playable
            if self.draw_play_card is not None and viewer == self.current_player():
                data['draw_play'] = True

        if self.state == 'finished':
            data['winner'] = self.winner
            data['scores'] = self.scores

        return data

    def get_table_data(self) -> dict:
        """等待室数据"""
        return {
            'game_type': 'uno',
            'room_id': self.room_id,
            'room_state': self.state,
            'players': self.players,
            'host': self.host,
            'max_players': self.max_players,
            'ranked': self.ranked,
            'draw_stacking': self.draw_stacking,
            'challenge_enabled': self.challenge_enabled,
        }

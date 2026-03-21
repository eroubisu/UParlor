"""麻将房间 — 管理座位、牌局、判定

一个 MahjongRoom 承载一局麻将的完整状态：
牌山、各家手牌/河/副露、轮次、风向、分数、立直。
判定逻辑使用 mahjong 第三方库 (HandCalculator / Shanten)。
"""

from __future__ import annotations

import random

from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from mahjong.meld import Meld
from mahjong.shanten import Shanten

from .tiles import (
    tile_to_str, tile_to_chinese, hand_to_34,
    POSITION_NAMES, WIND_NAMES,
)

MAX_PLAYERS = 4
HAND_SIZE = 13
INITIAL_SCORE = 25000

_calculator = HandCalculator()
_shanten = Shanten()

# 默认可选规则
_OPTIONAL = OptionalRules(
    has_open_tanyao=True,
    has_aka_dora=False,
)


def _indicator_to_dora_34(tile_136: int) -> int:
    """宝牌指示牌 → 实际宝牌的34编码

    规则: 数牌 1→2→...→9→1, 风牌 東→南→西→北→東, 三元 白→發→中→白
    """
    t34 = tile_136 // 4
    if t34 < 27:
        # 数牌: 同花色内 +1, 9→1
        suit_base = (t34 // 9) * 9
        return suit_base + (t34 - suit_base + 1) % 9
    if t34 < 31:
        # 风牌: 27東→28南→29西→30北→27東
        return 27 + (t34 - 27 + 1) % 4
    # 三元: 31白→32發→33中→31白
    return 31 + (t34 - 31 + 1) % 3


class MahjongRoom:
    """麻将房间

    状态机: waiting → playing → finished → waiting (继续下一局)
    """

    def __init__(self, room_id: str, host: str):
        self.room_id = room_id
        self.host = host
        self.state = 'waiting'
        self.players: list[str | None] = [host, None, None, None]
        self.bots: set[str] = set()

        # ── 对局设置 ──
        self.game_mode = 'east'        # east=东风战 / south=南风战
        self.room_tier = 'friendly'    # friendly=友人場 / bronze=铜之间 / silver=银之间 / gold=金之间
        self.round_wind: int = 0       # 场风 (0=东, 1=南)
        self.round_number: int = 0     # 局数 (0=东一局, 1=东二局, ..)
        self.honba: int = 0            # 本场数
        self.riichi_sticks: int = 0    # 供托(立直棒数)
        self.dealer: int = 0           # 亲家座位

        # ── 牌局状态 ──
        self.wall: list[int] = []
        self.dead_wall: list[int] = []        # 王牌 (14张)
        self.dora_indicators: list[int] = []  # 宝牌指示牌
        self.hands: list[list[int]] = [[], [], [], []]
        self.discards: list[list[int]] = [[], [], [], []]
        self.melds: list[list[list[int]]] = [[], [], [], []]
        self.meld_types: list[list[str]] = [[], [], [], []]  # 副露类型
        self.current_turn: int = 0
        self.drawn_tile: int | None = None
        self.scores: list[int] = [INITIAL_SCORE] * 4
        self.riichi: list[bool] = [False] * 4
        self.ippatsu: list[bool] = [False] * 4  # 一发标记
        self.turn_count: int = 0
        self._pending_action: dict | None = None
        self._riichi_pending: dict | None = None  # {seat, valid_indices}

        # ── 机器人自摸缓存 ──
        self.last_win_info: dict | None = None
        self.last_winner_seat: int | None = None
        self.last_win_message: str | None = None

    # ── 座位管理 ──

    def get_player_count(self) -> int:
        return sum(1 for p in self.players if p is not None)

    def is_full(self) -> bool:
        return self.get_player_count() >= MAX_PLAYERS

    def is_bot(self, name: str) -> bool:
        return name in self.bots

    def get_position(self, name: str) -> int:
        for i, p in enumerate(self.players):
            if p == name:
                return i
        return -1

    def add_player(self, name: str) -> tuple[bool, str]:
        for i, p in enumerate(self.players):
            if p is None:
                self.players[i] = name
                return True, POSITION_NAMES[i]
        return False, '房间已满'

    def remove_player(self, name: str) -> int:
        for i, p in enumerate(self.players):
            if p == name:
                self.players[i] = None
                return i
        return -1

    def add_bot(self) -> tuple[bool, str]:
        for i, p in enumerate(self.players):
            if p is None:
                bot_name = f"Bot_{POSITION_NAMES[i]}"
                self.players[i] = bot_name
                self.bots.add(bot_name)
                return True, bot_name
        return False, '房间已满'

    # ── 对局控制 ──

    def start_game(self):
        """开始整场对局 (从东一局开始)"""
        self.state = 'playing'
        self.round_wind = 0
        self.round_number = 0
        self.honba = 0
        self.riichi_sticks = 0
        self.dealer = 0
        self.scores = [INITIAL_SCORE] * 4
        self._deal()

    def start_next_round(self):
        """开始下一局"""
        self.state = 'playing'
        self._clear_bot_cache()
        self._deal()

    def advance_round(self, dealer_won: bool):
        """推进局数

        dealer_won=True: 连庄 (honba+1, dealer 不变)
        dealer_won=False: 亲家下移, round_number+1
        """
        if dealer_won:
            self.honba += 1
        else:
            self.dealer = (self.dealer + 1) % 4
            self.round_number += 1
            self.honba = 0
            # 如果 round_number >= 4 说明这一场风结束
            if self.round_number >= 4:
                self.round_wind += 1
                self.round_number = 0

    def is_game_over(self) -> bool:
        """整场对局是否结束"""
        max_wind = 1 if self.game_mode == 'east' else 2
        if self.round_wind >= max_wind:
            return True
        # 有人分数 < 0 也结束
        if any(s < 0 for s in self.scores):
            return True
        return False

    def get_round_name(self) -> str:
        """如 '东一局', '南三局'"""
        wind = WIND_NAMES[self.round_wind]
        num = ['一', '二', '三', '四'][self.round_number % 4]
        suffix = f' {self.honba}本場' if self.honba > 0 else ''
        return f'{wind}{num}局{suffix}'

    def get_seat_wind(self, seat: int) -> int:
        """获取某座位的自风 (相对于亲家)"""
        return (seat - self.dealer) % 4

    def _deal(self):
        """发牌"""
        self.wall = list(range(136))
        random.shuffle(self.wall)
        # 王牌: 先取出14张作为死牌
        self.dead_wall = self.wall[-14:]
        self.wall = self.wall[:-14]
        # 宝牌指示牌: 王牌第5张
        self.dora_indicators = [self.dead_wall[4]]
        for i in range(4):
            self.hands[i] = sorted(self.wall[:HAND_SIZE], key=lambda t: t // 4)
            self.wall = self.wall[HAND_SIZE:]
        self.discards = [[], [], [], []]
        self.melds = [[], [], [], []]
        self.meld_types = [[], [], [], []]
        self.riichi = [False] * 4
        self.ippatsu = [False] * 4
        self.current_turn = self.dealer
        self.turn_count = 0
        self.drawn_tile = None
        self._pending_action = None
        self._riichi_pending = None
        self._clear_bot_cache()
        self._draw_tile(self.dealer)

    def _clear_bot_cache(self):
        self.last_win_info = None
        self.last_winner_seat = None
        self.last_win_message = None

    # ── 牌操作 ──

    def _draw_tile(self, seat: int) -> int | None:
        if not self.wall:
            return None
        tile = self.wall.pop(0)
        self.drawn_tile = tile
        return tile

    def discard_tile(self, seat: int, tile_136: int) -> bool:
        """打出一张牌"""
        hand = self.hands[seat]
        if self.drawn_tile is not None and tile_136 == self.drawn_tile:
            self.drawn_tile = None
        elif tile_136 in hand:
            hand.remove(tile_136)
            if self.drawn_tile is not None:
                hand.append(self.drawn_tile)
                hand.sort(key=lambda t: t // 4)
                self.drawn_tile = None
        else:
            return False
        self.discards[seat].append(tile_136)
        self.turn_count += 1
        # 出牌后一发消失
        self.ippatsu[seat] = False
        return True

    def get_full_hand(self, seat: int) -> list[int]:
        hand = list(self.hands[seat])
        if self.drawn_tile is not None and self.current_turn == seat:
            hand.append(self.drawn_tile)
        return hand

    def next_turn(self):
        # 其他家的一发在一巡后消失
        for i in range(4):
            if i != self.current_turn:
                self.ippatsu[i] = False
        self.current_turn = (self.current_turn + 1) % 4
        self._draw_tile(self.current_turn)

    def is_draw(self) -> bool:
        return len(self.wall) == 0

    # ── 副露操作 ──

    def do_pon(self, seat: int, tile_136: int):
        tile_34 = tile_136 // 4
        taken = []
        hand = self.hands[seat]
        for _ in range(2):
            for t in hand:
                if t // 4 == tile_34:
                    taken.append(t)
                    hand.remove(t)
                    break
        taken.append(tile_136)
        self.melds[seat].append(taken)
        self.meld_types[seat].append('pon')

    def do_chi(self, seat: int, tile_136: int, combo_tiles: list[int]):
        hand = self.hands[seat]
        meld = [tile_136]
        for t in combo_tiles:
            hand.remove(t)
            meld.append(t)
        self.melds[seat].append(meld)
        self.meld_types[seat].append('chi')

    def do_riichi(self, seat: int):
        self.riichi[seat] = True
        self.ippatsu[seat] = True
        self.scores[seat] -= 1000
        self.riichi_sticks += 1

    def can_riichi(self, seat: int) -> bool:
        """检查能否立直"""
        if self.riichi[seat]:
            return False
        if self.melds[seat]:  # 有副露不能立直
            return False
        if self.scores[seat] < 1000:
            return False
        if self.drawn_tile is None:
            return False
        # 检查是否听牌（向听数为0）
        full = self.get_full_hand(seat)
        # 尝试每张牌打出后是否听牌
        for t in full:
            test = [x for x in full if x != t]
            tiles_34 = hand_to_34(test)
            try:
                sh = _shanten.calculate_shanten(tiles_34)
                if sh == 0:
                    return True
            except Exception:
                pass
        return False

    def get_riichi_options(self, seat: int) -> list[dict]:
        """计算立直时可打出的牌及其听牌信息

        返回 [{idx, tile_136, tile_chinese, waiting: [{name, remaining, points}]}]
        仅返回打出后能听牌(shanten=0)的选项。
        """
        full = self.get_full_hand(seat)
        sorted_hand = sorted(list(self.hands[seat]), key=lambda t: t // 4)
        if self.drawn_tile is not None and self.current_turn == seat:
            sorted_hand.append(self.drawn_tile)

        # 收集所有已公开的牌用于计算剩余张数
        visible = [0] * 34
        for i in range(4):
            for t in self.discards[i]:
                visible[t // 4] += 1
            for m in self.melds[i]:
                for t in m:
                    visible[t // 4] += 1
        # 自己手牌也算已知
        for t in sorted_hand:
            visible[t // 4] += 1

        options = []
        seen_t34 = set()  # 避免同 34 编码重复计算
        for idx, t in enumerate(sorted_hand):
            t34 = t // 4
            if t34 in seen_t34:
                continue
            # 打出这张后的手牌
            test = [x for x in sorted_hand if x != t]
            if len(test) == len(sorted_hand):
                continue  # 没找到, 不应该发生
            test_34 = hand_to_34(test)
            try:
                sh = _shanten.calculate_shanten(test_34)
            except Exception:
                continue
            if sh != 0:
                continue
            seen_t34.add(t34)

            # 找出听的牌
            waiting = []
            for w34 in range(34):
                if test_34[w34] >= 4:
                    continue
                test_34[w34] += 1
                try:
                    if _shanten.calculate_shanten(test_34) == -1:
                        remaining = 4 - visible[w34]
                        # visible 中包含了要打出的牌, 但打出后它变成弃牌
                        # 已经在 visible 中了(因为来自 sorted_hand), 打出后
                        # 不在手中但在弃牌→仍然不可用, 所以 remaining 不变
                        if remaining > 0:
                            # 估算和牌点数
                            pts = self._estimate_win_points(
                                seat, test, w34)
                            waiting.append({
                                'name': tile_to_chinese(w34 * 4),
                                'remaining': remaining,
                                'points': pts,
                            })
                except Exception:
                    pass
                test_34[w34] -= 1

            if waiting:
                options.append({
                    'idx': idx + 1,
                    'tile_136': t,
                    'tile_chinese': tile_to_chinese(t),
                    'waiting': waiting,
                })
        return options

    def _estimate_win_points(self, seat: int, hand_136: list[int],
                             win_tile_34: int) -> int:
        """粗略估算以立直和牌的点数"""
        win_tile = win_tile_34 * 4
        full = hand_136 + [win_tile]
        try:
            config = HandConfig(
                is_tsumo=True,
                is_riichi=True,
                round_wind=self.round_wind,
                player_wind=self.get_seat_wind(seat),
                options=_OPTIONAL,
            )
            result = _calculator.estimate_hand_value(
                full, win_tile, config=config,
                dora_indicators=self.dora_indicators)
            if result.error:
                return 0
            return result.cost['main'] + result.cost.get('additional', 0)
        except Exception:
            return 0

    # ── 判定 ──

    def _build_melds_for_calc(self, seat: int) -> list[Meld]:
        """构建 mahjong 库需要的 Meld 对象列表"""
        result = []
        for idx, tiles in enumerate(self.melds[seat]):
            if idx < len(self.meld_types[seat]):
                mtype = self.meld_types[seat][idx]
            else:
                mtype = 'pon'
            if mtype == 'chi':
                result.append(Meld(meld_type=Meld.CHI, tiles=tiles, opened=True))
            elif mtype == 'kan':
                result.append(Meld(meld_type=Meld.KAN, tiles=tiles, opened=True))
            else:
                result.append(Meld(meld_type=Meld.PON, tiles=tiles, opened=True))
        return result

    def _make_config(self, seat: int, is_tsumo: bool) -> HandConfig:
        """构建 HandConfig，传入风位、立直等状态"""
        seat_wind = self.get_seat_wind(seat)
        return HandConfig(
            is_tsumo=is_tsumo,
            is_riichi=self.riichi[seat],
            is_ippatsu=self.ippatsu[seat],
            round_wind=self.round_wind,
            player_wind=seat_wind,
            is_haitei=is_tsumo and len(self.wall) == 0,
            is_houtei=not is_tsumo and len(self.wall) == 0,
            tsumi_number=self.honba,
            kyoutaku_number=self.riichi_sticks,
            options=_OPTIONAL,
        )

    def check_tsumo(self, seat: int) -> dict | None:
        if self.drawn_tile is None:
            return None
        full = self.get_full_hand(seat)
        # 加上副露牌给库（库要求 tiles 包含所有 14 张）
        lib_tiles = list(full)
        for m in self.melds[seat]:
            lib_tiles.extend(m)
        tiles_34 = hand_to_34(lib_tiles)
        if _shanten.calculate_shanten(tiles_34) != -1:
            return None
        try:
            config = self._make_config(seat, is_tsumo=True)
            melds = self._build_melds_for_calc(seat)
            result = _calculator.estimate_hand_value(
                lib_tiles, self.drawn_tile, melds=melds, config=config,
                dora_indicators=self.dora_indicators)
            if result.error:
                return None
            return {
                'han': result.han,
                'fu': result.fu,
                'cost': result.cost['main'],
                'cost_additional': result.cost.get('additional', 0),
                'yaku': [str(y) for y in result.yaku],
            }
        except Exception:
            return None

    def check_ron(self, seat: int, tile_136: int) -> dict | None:
        full = list(self.hands[seat]) + [tile_136]
        # 加上副露牌给库（库要求 tiles 包含所有 14 张）
        lib_tiles = list(full)
        for m in self.melds[seat]:
            lib_tiles.extend(m)
        tiles_34 = hand_to_34(lib_tiles)
        if _shanten.calculate_shanten(tiles_34) != -1:
            return None
        try:
            config = self._make_config(seat, is_tsumo=False)
            melds = self._build_melds_for_calc(seat)
            result = _calculator.estimate_hand_value(
                lib_tiles, tile_136, melds=melds, config=config,
                dora_indicators=self.dora_indicators)
            if result.error:
                return None
            return {
                'han': result.han,
                'fu': result.fu,
                'cost': result.cost['main'],
                'cost_additional': result.cost.get('additional', 0),
                'yaku': [str(y) for y in result.yaku],
            }
        except Exception:
            return None

    def can_pon(self, seat: int, tile_136: int) -> bool:
        tile_34 = tile_136 // 4
        count = sum(1 for t in self.hands[seat] if t // 4 == tile_34)
        return count >= 2

    def can_chi(self, seat: int, tile_136: int, from_seat: int) -> bool:
        if (from_seat + 1) % 4 != seat:
            return False
        tile_34 = tile_136 // 4
        if tile_34 >= 27:
            return False
        suit_base = (tile_34 // 9) * 9
        num = tile_34 - suit_base
        hand_34 = set(t // 4 for t in self.hands[seat])
        if num >= 2 and (tile_34 - 2) in hand_34 and (tile_34 - 1) in hand_34:
            return True
        if 1 <= num <= 7 and (tile_34 - 1) in hand_34 and (tile_34 + 1) in hand_34:
            return True
        if num <= 6 and (tile_34 + 1) in hand_34 and (tile_34 + 2) in hand_34:
            return True
        return False

    # ── 计分 ──

    def apply_win(self, winner_seat: int, win_info: dict, is_tsumo: bool,
                  from_seat: int | None = None):
        """应用和牌计分 (含本场/供托)"""
        cost = win_info['cost']
        honba_bonus = self.honba * 300

        if is_tsumo:
            cost_add = win_info.get('cost_additional', 0)
            if self.dealer == winner_seat:
                # 亲家自摸: 子各付 cost/3 + 本场
                each = cost // 3 + (honba_bonus // 3)
                for i in range(4):
                    if i != winner_seat:
                        self.scores[i] -= each
                self.scores[winner_seat] += each * 3
            else:
                # 子家自摸: 亲付 cost, 其余付 cost_additional + 本场
                dealer_pay = cost + (honba_bonus // 3)
                other_pay = (cost_add if cost_add else cost // 3) + (honba_bonus // 3)
                for i in range(4):
                    if i == winner_seat:
                        continue
                    if i == self.dealer:
                        self.scores[i] -= dealer_pay
                    else:
                        self.scores[i] -= other_pay
                self.scores[winner_seat] += dealer_pay + other_pay * 2
        else:
            # 荣和: 放铳者付全额 + 本场
            total = cost + honba_bonus
            if from_seat is not None:
                self.scores[from_seat] -= total
            self.scores[winner_seat] += total

        # 供托归赢家
        self.scores[winner_seat] += self.riichi_sticks * 1000
        self.riichi_sticks = 0

    def apply_draw(self):
        """流局 — 听牌者从未听牌者处获得点数"""
        tenpai = []
        noten = []
        for i in range(4):
            full = self.get_full_hand(i)
            tiles_34 = hand_to_34(full)
            try:
                sh = _shanten.calculate_shanten(tiles_34)
                if sh <= 0:
                    tenpai.append(i)
                else:
                    noten.append(i)
            except Exception:
                noten.append(i)

        if tenpai and noten:
            total = 3000
            pay_each = total // len(noten)
            recv_each = total // len(tenpai)
            for i in noten:
                self.scores[i] -= pay_each
            for i in tenpai:
                self.scores[i] += recv_each

    # ── 数据序列化 ──

    def get_table_data(self) -> dict:
        return {
            'game_type': 'mahjong',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'game_mode': self.game_mode,
            'room_tier': self.room_tier,
            'round_name': self.get_round_name(),
            'players': [
                {'name': p, 'position': POSITION_NAMES[i],
                 'score': self.scores[i],
                 'is_bot': p in self.bots if p else False}
                for i, p in enumerate(self.players)
            ],
            'max_players': MAX_PLAYERS,
        }

    def get_game_data(self, seat: int) -> dict:
        hand = list(self.hands[seat])
        sorted_hand = sorted(hand, key=lambda t: t // 4)
        # 新摸的牌放在最后（纵向显示时在最下面）
        if self.drawn_tile is not None and self.current_turn == seat:
            sorted_hand.append(self.drawn_tile)
        hand_strs = [tile_to_str(t) for t in sorted_hand]
        hand_chinese = [tile_to_chinese(t) for t in sorted_hand]

        data = {
            'game_type': 'mahjong',
            'room_id': self.room_id,
            'room_state': 'playing',
            'seat': seat,
            'position': POSITION_NAMES[seat],
            'hand': hand_strs,
            'hand_chinese': hand_chinese,
            'hand_136': sorted_hand,
            'drawn': (
                tile_to_chinese(self.drawn_tile)
                if self.drawn_tile is not None
                and self.current_turn == seat
                else None
            ),
            'discards': [
                [tile_to_str(t) for t in self.discards[i]]
                for i in range(4)
            ],
            'discards_chinese': [
                [tile_to_chinese(t) for t in self.discards[i]]
                for i in range(4)
            ],
            'melds': [
                [[tile_to_str(t) for t in m] for m in self.melds[i]]
                for i in range(4)
            ],
            'players': [
                {'name': p, 'position': POSITION_NAMES[i],
                 'score': self.scores[i],
                 'riichi': self.riichi[i],
                 'is_bot': p in self.bots if p else False}
                for i, p in enumerate(self.players)
            ],
            'current_turn': self.current_turn,
            'my_turn': self.current_turn == seat and not self._pending_action,
            'round_name': self.get_round_name(),
            'round_wind': WIND_NAMES[self.round_wind],
            'dealer': self.dealer,
            'honba': self.honba,
            'riichi_sticks': self.riichi_sticks,
            'wall_remaining': len(self.wall),
            'dora_indicators': [tile_to_chinese(t) for t in self.dora_indicators],
            'dora_indicators_str': [tile_to_str(t) for t in self.dora_indicators],
            'dora_tiles_34': [_indicator_to_dora_34(t) for t in self.dora_indicators],
        }

        # 向听数 + 待ち牌
        tiles_34 = hand_to_34(sorted_hand)
        shanten = _shanten.calculate_shanten(tiles_34)
        data['shanten'] = shanten

        if shanten == 0:
            # 収集已公开的牌，用于计算剩余张数
            visible = [0] * 34
            for i in range(4):
                for t in self.discards[i]:
                    visible[t // 4] += 1
                for m in self.melds[i]:
                    for t in m:
                        visible[t // 4] += 1
            for t in sorted_hand:
                visible[t // 4] += 1

            # 聴牌: 找出哪些牌能让向听变为 -1 (和牌)
            waiting = []
            for t34 in range(34):
                if tiles_34[t34] >= 4:
                    continue
                tiles_34[t34] += 1
                try:
                    if _shanten.calculate_shanten(tiles_34) == -1:
                        remaining = 4 - visible[t34]
                        if remaining <= 0:
                            tiles_34[t34] -= 1
                            continue
                        w_info = {'name': tile_to_chinese(t34 * 4),
                                  'remaining': remaining}
                        # 估算和牌番数/点数
                        try:
                            win_tile = t34 * 4
                            full_win = list(sorted_hand) + [win_tile]
                            config = self._make_config(seat, is_tsumo=True)
                            melds = self._build_melds_for_calc(seat)
                            result = _calculator.estimate_hand_value(
                                full_win, win_tile, melds=melds,
                                config=config,
                                dora_indicators=self.dora_indicators)
                            if not result.error:
                                w_info['han'] = result.han
                                w_info['fu'] = result.fu
                                w_info['points'] = (
                                    result.cost['main']
                                    + result.cost.get('additional', 0))
                        except Exception:
                            pass
                        waiting.append(w_info)
                except Exception:
                    pass
                tiles_34[t34] -= 1
            data['waiting_tiles'] = waiting

        elif shanten == 1 and self.current_turn == seat:
            # 一向听: 找出打哪张牌能进入听牌，以及听什么
            visible = [0] * 34
            for i in range(4):
                for t in self.discards[i]:
                    visible[t // 4] += 1
                for m in self.melds[i]:
                    for t in m:
                        visible[t // 4] += 1
            for t in sorted_hand:
                visible[t // 4] += 1

            tenpai_discards = []
            seen_t34 = set()
            for idx, t in enumerate(sorted_hand):
                t34 = t // 4
                if t34 in seen_t34:
                    continue
                test = [x for x in sorted_hand if x != t]
                if len(test) == len(sorted_hand):
                    continue
                test_34 = hand_to_34(test)
                try:
                    sh = _shanten.calculate_shanten(test_34)
                except Exception:
                    continue
                if sh != 0:
                    continue
                seen_t34.add(t34)

                waits = []
                for w34 in range(34):
                    if test_34[w34] >= 4:
                        continue
                    test_34[w34] += 1
                    try:
                        if _shanten.calculate_shanten(test_34) == -1:
                            remaining = 4 - visible[w34]
                            if remaining > 0:
                                waits.append({
                                    'name': tile_to_chinese(w34 * 4),
                                    'remaining': remaining,
                                })
                    except Exception:
                        pass
                    test_34[w34] -= 1
                if waits:
                    tenpai_discards.append({
                        'idx': idx + 1,
                        'tile_chinese': tile_to_chinese(t),
                        'waiting': waits,
                    })
            if tenpai_discards:
                data['tenpai_discards'] = tenpai_discards

        if self.current_turn == seat and self.drawn_tile is not None:
            tsumo = self.check_tsumo(seat)
            if tsumo:
                data['can_tsumo'] = True
            if self.can_riichi(seat):
                data['can_riichi'] = True

        return data

    def get_finished_data(self, winner_seat: int | None,
                          win_info: dict | None) -> dict:
        data = self.get_table_data()
        data['room_state'] = 'finished'
        data['finished'] = True
        data['round_name'] = self.get_round_name()
        if winner_seat is not None and win_info:
            data['winner'] = self.players[winner_seat]
            data['winner_position'] = POSITION_NAMES[winner_seat]
            data['win_info'] = win_info
        else:
            data['draw'] = True
        data['all_hands'] = [
            [tile_to_str(t) for t in sorted(self.hands[i], key=lambda t: t // 4)]
            for i in range(4)
        ]
        data['all_hands_chinese'] = [
            [tile_to_chinese(t) for t in sorted(self.hands[i], key=lambda t: t // 4)]
            for i in range(4)
        ]
        data['dora_indicators'] = [tile_to_chinese(t) for t in self.dora_indicators]
        data['dora_indicators_str'] = [tile_to_str(t) for t in self.dora_indicators]
        return data

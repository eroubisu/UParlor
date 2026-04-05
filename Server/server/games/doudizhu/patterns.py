"""斗地主牌型识别与比较

牌力排序 (rank in cards/deck.py):
  3=2, 4=3, 5=4, 6=5, 7=6, 8=7, 9=8, 10=9, J=10, Q=11, K=12, A=13, 2=14
  小王=15, 大王=16

为简化比较，这里用 doudizhu_rank(card) 把原始 rank 映射为斗地主权重:
  3→3, 4→4, ..., K→13, A→14, 2→15, 小王→16, 大王→17

牌型枚举 (type_id, name):
  0  PASS       不出 (过)
  1  SINGLE     单张
  2  PAIR       对子
  3  TRIPLE     三条
  4  TRIPLE_1   三带一
  5  TRIPLE_2   三带二 (一对)
  6  STRAIGHT   顺子 (≥5张连续单张，不含2和王)
  7  STRAIGHT_PAIR  连对 (≥3对连续对子)
  8  PLANE      飞机 (≥2组连续三条)
  9  PLANE_1    飞机带单翼 (每组带一张)
  10 PLANE_2    飞机带双翼 (每组带一对)
  11 FOUR_2     四带二 (四张+两张单 或 四张+两对)
  12 BOMB       炸弹 (四张相同)
  13 ROCKET     火箭 (双王)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..cards.deck import Card

# 牌型 ID
PASS = 0
SINGLE = 1
PAIR = 2
TRIPLE = 3
TRIPLE_1 = 4
TRIPLE_2 = 5
STRAIGHT = 6
STRAIGHT_PAIR = 7
PLANE = 8
PLANE_1 = 9
PLANE_2 = 10
FOUR_2 = 11
BOMB = 12
ROCKET = 13

TYPE_NAMES = {
    PASS: '不出', SINGLE: '单张', PAIR: '对子', TRIPLE: '三条',
    TRIPLE_1: '三带一', TRIPLE_2: '三带二', STRAIGHT: '顺子',
    STRAIGHT_PAIR: '连对', PLANE: '飞机', PLANE_1: '飞机带翼',
    PLANE_2: '飞机带翼', FOUR_2: '四带二', BOMB: '炸弹',
    ROCKET: '火箭',
}


def doudizhu_rank(card: Card) -> int:
    """斗地主牌权重: 3→3, ..., K→13, A→14, 2→15, 小王→16, 大王→17"""
    r = card.rank
    if r >= 15:
        return r + 1  # 15→16, 16→17
    if r == 14:
        return 14  # A
    if r == 2:
        return 15  # 2 在斗地主中最大(普通牌)
    return r  # 3-13 保持不变


@dataclass(frozen=True, slots=True)
class Play:
    """一手牌的识别结果"""
    type_id: int
    main_rank: int  # 主体最小 rank (用于比较大小)
    length: int     # 主体连续长度 (顺子/连对/飞机)
    cards: tuple[Card, ...]

    @property
    def name(self) -> str:
        return TYPE_NAMES.get(self.type_id, '?')

    def beats(self, other: 'Play') -> bool:
        """self 能否打过 other"""
        if other.type_id == PASS:
            return True
        # 火箭 > 一切
        if self.type_id == ROCKET:
            return True
        if other.type_id == ROCKET:
            return False
        # 炸弹 > 非炸弹
        if self.type_id == BOMB and other.type_id != BOMB:
            return True
        if other.type_id == BOMB and self.type_id != BOMB:
            return False
        # 同类型 + 同长度才可比较
        if self.type_id != other.type_id:
            return False
        if self.length != other.length:
            return False
        return self.main_rank > other.main_rank


def identify(cards: list[Card]) -> Play | None:
    """识别一手牌的牌型，无效返回 None"""
    n = len(cards)
    if n == 0:
        return Play(PASS, 0, 0, ())

    ranks = [doudizhu_rank(c) for c in cards]
    cnt = Counter(ranks)
    sorted_cards = tuple(sorted(cards, key=lambda c: doudizhu_rank(c)))

    # 火箭
    if n == 2 and 16 in cnt and 17 in cnt:
        return Play(ROCKET, 16, 1, sorted_cards)

    # 炸弹
    if n == 4 and len(cnt) == 1:
        r = next(iter(cnt))
        return Play(BOMB, r, 1, sorted_cards)

    # 单张
    if n == 1:
        return Play(SINGLE, ranks[0], 1, sorted_cards)

    # 对子
    if n == 2 and len(cnt) == 1:
        r = next(iter(cnt))
        return Play(PAIR, r, 1, sorted_cards)

    # 三条
    if n == 3 and len(cnt) == 1:
        r = next(iter(cnt))
        return Play(TRIPLE, r, 1, sorted_cards)

    # 三带一
    if n == 4 and len(cnt) == 2:
        triples = [r for r, c in cnt.items() if c == 3]
        if len(triples) == 1:
            return Play(TRIPLE_1, triples[0], 1, sorted_cards)

    # 三带二 (一对)
    if n == 5 and len(cnt) == 2:
        triples = [r for r, c in cnt.items() if c == 3]
        pairs = [r for r, c in cnt.items() if c == 2]
        if len(triples) == 1 and len(pairs) == 1:
            return Play(TRIPLE_2, triples[0], 1, sorted_cards)

    # 顺子 (≥5 连续，不含 2(15) 和王(16,17))
    if n >= 5 and len(cnt) == n and all(c == 1 for c in cnt.values()):
        sorted_ranks = sorted(cnt.keys())
        if (sorted_ranks[-1] - sorted_ranks[0] == n - 1
                and all(r <= 14 for r in sorted_ranks)):
            return Play(STRAIGHT, sorted_ranks[0], n, sorted_cards)

    # 连对 (≥3 对连续)
    if n >= 6 and n % 2 == 0 and all(c == 2 for c in cnt.values()):
        pair_count = n // 2
        sorted_ranks = sorted(cnt.keys())
        if (len(sorted_ranks) == pair_count
                and sorted_ranks[-1] - sorted_ranks[0] == pair_count - 1
                and all(r <= 14 for r in sorted_ranks)):
            return Play(STRAIGHT_PAIR, sorted_ranks[0], pair_count, sorted_cards)

    # 飞机系列 (≥2 连续三条)
    triples = sorted(r for r, c in cnt.items() if c >= 3)
    if len(triples) >= 2:
        # 找最长连续三条序列 (不含 2 和王)
        chain = _longest_consecutive(triples, max_rank=14)
        if chain:
            chain_len = len(chain)
            chain_total = chain_len * 3
            remaining = n - chain_total

            # 纯飞机
            if remaining == 0:
                return Play(PLANE, chain[0], chain_len, sorted_cards)

            # 飞机带单翼
            if remaining == chain_len:
                return Play(PLANE_1, chain[0], chain_len, sorted_cards)

            # 飞机带双翼 (附属必须是对子)
            if remaining == chain_len * 2:
                # 剩余部分的 rank 计数
                rest_cnt = Counter(ranks)
                for r in chain:
                    rest_cnt[r] -= 3
                # 去掉 0 count
                rest_ranks = {r: c for r, c in rest_cnt.items() if c > 0}
                # 每个附属至少 2 张 (可以来自多个 rank)
                if all(c >= 2 for c in rest_ranks.values()):
                    pair_total = sum(c // 2 for c in rest_ranks.values())
                    if pair_total >= chain_len:
                        return Play(PLANE_2, chain[0], chain_len, sorted_cards)

    # 四带二
    fours = [r for r, c in cnt.items() if c == 4]
    if len(fours) == 1:
        four_rank = fours[0]
        remaining = n - 4
        if remaining == 2:
            # 四带两张单 或 四带一对
            return Play(FOUR_2, four_rank, 1, sorted_cards)
        if remaining == 4:
            # 四带两对
            rest_cnt = Counter(ranks)
            rest_cnt[four_rank] -= 4
            rest_ranks = {r: c for r, c in rest_cnt.items() if c > 0}
            if all(c == 2 for c in rest_ranks.values()) and len(rest_ranks) == 2:
                return Play(FOUR_2, four_rank, 1, sorted_cards)

    return None


def _longest_consecutive(sorted_ranks: list[int], max_rank: int = 14) -> list[int] | None:
    """从排序序列中找最长连续子序列 (rank ≤ max_rank)，长度 ≥ 2"""
    filtered = [r for r in sorted_ranks if r <= max_rank]
    if len(filtered) < 2:
        return None

    best: list[int] = []
    current = [filtered[0]]
    for i in range(1, len(filtered)):
        if filtered[i] == filtered[i - 1] + 1:
            current.append(filtered[i])
        else:
            if len(current) > len(best):
                best = current
            current = [filtered[i]]
    if len(current) > len(best):
        best = current

    return best if len(best) >= 2 else None


def sort_hand(cards: list[Card]) -> list[Card]:
    """按斗地主规则排序手牌 (大→小)"""
    return sorted(cards, key=lambda c: doudizhu_rank(c), reverse=True)


def find_all_beats(
    hand: list[Card], last_play: Play,
) -> list[dict]:
    """找出手牌中所有能压过 last_play 的出法。

    Returns
    -------
    plays: 每项 {'indices': [...], 'cards': [...], 'type': '...'}
           最末固定为 {'type': 'pass', 'indices': []}
    """
    if last_play.type_id == ROCKET:
        return [{'type': 'pass', 'indices': []}]

    # rank → hand indices 映射
    rmap: dict[int, list[int]] = {}
    for i, c in enumerate(hand):
        rmap.setdefault(doudizhu_rank(c), []).append(i)
    cnt = {r: len(v) for r, v in rmap.items()}

    results: list[dict] = []
    t = last_play.type_id
    mr = last_play.main_rank
    ln = last_play.length

    # ---- 同类型出法 ----
    if t == SINGLE:
        # 单张太多，不逐一列出，标记 single_only
        has_single = any(r > mr for r in cnt)
        if has_single:
            results.append({'type': 'single_hint', 'indices': []})

    elif t == PAIR:
        for r in sorted(rmap):
            if r > mr and cnt[r] >= 2:
                idxs = rmap[r][:2]
                results.append(_sug(hand, idxs, PAIR))

    elif t == TRIPLE:
        for r in sorted(rmap):
            if r > mr and cnt[r] >= 3:
                results.append(_sug(hand, rmap[r][:3], TRIPLE))

    elif t == TRIPLE_1:
        for r in sorted(rmap):
            if r > mr and cnt[r] >= 3:
                tri = rmap[r][:3]
                k = _pick_kickers(hand, rmap, set(tri), 1)
                if k is not None:
                    results.append(_sug(hand, tri + k, TRIPLE_1))

    elif t == TRIPLE_2:
        for r in sorted(rmap):
            if r > mr and cnt[r] >= 3:
                tri = rmap[r][:3]
                k = _pick_pair_kickers(hand, rmap, set(tri), 1)
                if k is not None:
                    results.append(_sug(hand, tri + k, TRIPLE_2))

    elif t == STRAIGHT:
        for start in range(mr + 1, 15 - ln + 1):
            needed = range(start, start + ln)
            if all(cnt.get(r, 0) >= 1 for r in needed):
                results.append(_sug(hand, [rmap[r][0] for r in needed], STRAIGHT))

    elif t == STRAIGHT_PAIR:
        for start in range(mr + 1, 15 - ln + 1):
            needed = range(start, start + ln)
            if all(cnt.get(r, 0) >= 2 for r in needed):
                idxs = []
                for r in needed:
                    idxs.extend(rmap[r][:2])
                results.append(_sug(hand, idxs, STRAIGHT_PAIR))

    elif t in (PLANE, PLANE_1, PLANE_2):
        tri_ranks = sorted(r for r in rmap if cnt[r] >= 3 and r <= 14)
        for seq in _consecutive_runs(tri_ranks, ln):
            if seq[0] <= mr:
                continue
            idxs: list[int] = []
            used: set[int] = set()
            for r in seq:
                for i in rmap[r][:3]:
                    idxs.append(i)
                    used.add(i)
            if t == PLANE:
                results.append(_sug(hand, idxs, PLANE))
            elif t == PLANE_1:
                k = _pick_kickers(hand, rmap, used, ln)
                if k is not None:
                    results.append(_sug(hand, idxs + k, PLANE_1))
            else:  # PLANE_2
                k = _pick_pair_kickers(hand, rmap, used, ln)
                if k is not None:
                    results.append(_sug(hand, idxs + k, PLANE_2))

    elif t == FOUR_2:
        for r in sorted(rmap):
            if r > mr and cnt[r] >= 4:
                four = rmap[r][:4]
                k = _pick_kickers(hand, rmap, set(four), 2)
                if k is not None:
                    results.append(_sug(hand, four + k, FOUR_2))

    elif t == BOMB:
        for r in sorted(rmap):
            if r > mr and cnt[r] >= 4:
                results.append(_sug(hand, rmap[r][:4], BOMB))

    # ---- 炸弹 (非同类型时) ----
    if t not in (BOMB, ROCKET):
        for r in sorted(rmap):
            if cnt[r] >= 4:
                results.append(_sug(hand, rmap[r][:4], BOMB))

    # ---- 火箭 ----
    jokers = [i for i, c in enumerate(hand) if doudizhu_rank(c) >= 16]
    if len(jokers) == 2:
        results.append(_sug(hand, jokers, ROCKET))

    # ---- pass 固定末尾 ----
    results.append({'type': 'pass', 'indices': []})
    return results


# ---------- helpers ----------

def _sug(hand: list[Card], indices: list[int], type_id: int) -> dict:
    return {
        'indices': indices,
        'type': TYPE_NAMES[type_id],
        'cards': [hand[i].name for i in indices],
    }


def _pick_kickers(
    hand: list[Card], rmap: dict[int, list[int]],
    used: set[int], count: int,
) -> list[int] | None:
    """选最小的 count 张不在 used 中的牌作为带牌"""
    picks: list[int] = []
    for r in sorted(rmap):
        for i in rmap[r]:
            if i not in used:
                picks.append(i)
                if len(picks) == count:
                    return picks
    return None


def _pick_pair_kickers(
    hand: list[Card], rmap: dict[int, list[int]],
    used: set[int], pair_count: int,
) -> list[int] | None:
    """选最小的 pair_count 对不在 used 中的牌"""
    picks: list[int] = []
    for r in sorted(rmap):
        avail = [i for i in rmap[r] if i not in used]
        if len(avail) >= 2:
            picks.extend(avail[:2])
            if len(picks) >= pair_count * 2:
                return picks[:pair_count * 2]
    return None


def _consecutive_runs(sorted_ranks: list[int], min_len: int):
    """生成所有长度 >= min_len 的连续子序列"""
    if len(sorted_ranks) < min_len:
        return
    run = [sorted_ranks[0]]
    for i in range(1, len(sorted_ranks)):
        if sorted_ranks[i] == run[-1] + 1:
            run.append(sorted_ranks[i])
        else:
            if len(run) >= min_len:
                for off in range(len(run) - min_len + 1):
                    yield run[off:off + min_len]
            run = [sorted_ranks[i]]
    if len(run) >= min_len:
        for off in range(len(run) - min_len + 1):
            yield run[off:off + min_len]

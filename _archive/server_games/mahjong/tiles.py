"""麻将牌工具函数 — 编码转换、显示、解析

136编码: 0-135 (每种牌4张)
34编码:  0-33  (万0-8, 筒9-17, 索18-26, 字27-33)
"""

from __future__ import annotations

# 字牌名映射（繁體）
HONOR_NAMES = {0: '東', 1: '南', 2: '西', 3: '北', 4: '白', 5: '發', 6: '中'}
WIND_NAMES = ['東', '南', '西', '北']
POSITION_NAMES = ['東', '南', '西', '北']

# 花色颜色（用于客户端渲染）
SUIT_COLORS = {
    'm': '#4a9aef',   # 万子 蓝
    'p': '#ef6a4a',   # 筒子 红
    's': '#4aaf5a',   # 索子 绿
    'z': '#c8b060',   # 字牌 金
}

_HONOR_PARSE = {
    '東': 27, '南': 28, '西': 29, '北': 30, '白': 31, '發': 32, '中': 33,
    '东': 27, '发': 32,  # 简体兼容
}

_NUM_CHINESE = ['一', '二', '三', '四', '五', '六', '七', '八', '九']
_SUIT_CHINESE = {0: '萬', 1: '筒', 2: '條'}

# 中文名 → 34编码 反向映射
_CHINESE_NUM_PARSE = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '七': 6, '八': 7, '九': 8}
_CHINESE_SUIT_PARSE = {'萬': 0, '筒': 1, '條': 2, '万': 0, '索': 2, '条': 2}  # 简体兼容


def tile_to_str(tile_136: int) -> str:
    """136编码 → 简短字符串 (如 1m, 5p, 7s, 东, 中)"""
    tile_34 = tile_136 // 4
    if tile_34 < 9:
        return f"{tile_34 + 1}m"
    if tile_34 < 18:
        return f"{tile_34 - 9 + 1}p"
    if tile_34 < 27:
        return f"{tile_34 - 18 + 1}s"
    return HONOR_NAMES.get(tile_34 - 27, '?')


def tile_to_chinese(tile_136: int) -> str:
    """136编码 → 中文名 (如 一万, 五筒, 七索, 东, 中)"""
    tile_34 = tile_136 // 4
    suit = tile_34 // 9
    if suit < 3:
        num = tile_34 - suit * 9
        return f'{_NUM_CHINESE[num]}{_SUIT_CHINESE[suit]}'
    return HONOR_NAMES.get(tile_34 - 27, '?')


def tile_suit(tile_str: str) -> str:
    """牌字符串 → 花色字母 (m/p/s/z)"""
    if len(tile_str) == 2 and tile_str[1] in ('m', 'p', 's'):
        return tile_str[1]
    return 'z'


def str_to_tile34(s: str) -> int | None:
    """字符串 → 34编码。如 '1m'→0, '5p'→13, '东'→27, '一万'→0"""
    s = s.strip()
    # 中文格式: 一万, 五筒, 七索
    if len(s) == 2 and s[0] in _CHINESE_NUM_PARSE and s[1] in _CHINESE_SUIT_PARSE:
        return _CHINESE_SUIT_PARSE[s[1]] * 9 + _CHINESE_NUM_PARSE[s[0]]
    if s in _HONOR_PARSE:
        return _HONOR_PARSE[s]
    s = s.lower()
    if len(s) == 2 and s[0].isdigit():
        num = int(s[0])
        if num < 1 or num > 9:
            return None
        suit = s[1]
        if suit == 'm':
            return num - 1
        if suit == 'p':
            return num + 8
        if suit == 's':
            return num + 17
    if len(s) == 2 and s[0].isdigit() and s[1] == 'z':
        num = int(s[0])
        if 1 <= num <= 7:
            return 26 + num
    return None


def hand_to_34(tiles_136: list[int]) -> list[int]:
    """136编码列表 → 34编码计数数组"""
    arr = [0] * 34
    for t in tiles_136:
        arr[t // 4] += 1
    return arr

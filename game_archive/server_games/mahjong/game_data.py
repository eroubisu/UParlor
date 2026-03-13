"""
麻将游戏数据
"""

# 麻将牌定义 - 使用竖排汉字风格
TILES = {
    # 万
    'wan': ['一万', '二万', '三万', '四万', '五万', '六万', '七万', '八万', '九万'],
    # 条
    'tiao': ['一条', '二条', '三条', '四条', '五条', '六条', '七条', '八条', '九条'],
    # 筒
    'tong': ['一筒', '二筒', '三筒', '四筒', '五筒', '六筒', '七筒', '八筒', '九筒'],
    # 字牌
    'zi': ['东', '南', '西', '北', '中', '发', '白']
}

# 赤宝牌 - 红色的5
RED_DORA = ['赤五万', '赤五条', '赤五筒']

# 牌的数值映射（用于顺子判断等）
TILE_INFO = {
    # 万子
    '一万': ('wan', 1), '二万': ('wan', 2), '三万': ('wan', 3),
    '四万': ('wan', 4), '五万': ('wan', 5), '六万': ('wan', 6),
    '七万': ('wan', 7), '八万': ('wan', 8), '九万': ('wan', 9),
    '赤五万': ('wan', 5),
    # 条子
    '一条': ('tiao', 1), '二条': ('tiao', 2), '三条': ('tiao', 3),
    '四条': ('tiao', 4), '五条': ('tiao', 5), '六条': ('tiao', 6),
    '七条': ('tiao', 7), '八条': ('tiao', 8), '九条': ('tiao', 9),
    '赤五条': ('tiao', 5),
    # 筒子
    '一筒': ('tong', 1), '二筒': ('tong', 2), '三筒': ('tong', 3),
    '四筒': ('tong', 4), '五筒': ('tong', 5), '六筒': ('tong', 6),
    '七筒': ('tong', 7), '八筒': ('tong', 8), '九筒': ('tong', 9),
    '赤五筒': ('tong', 5),
    # 字牌
    '东': ('zi', 1), '南': ('zi', 2), '西': ('zi', 3), '北': ('zi', 4),
    '中': ('zi', 5), '发': ('zi', 6), '白': ('zi', 7),
}

# 幺九牌（老头牌 + 字牌）
YAOJIU = ['一万', '九万', '一条', '九条', '一筒', '九筒', '东', '南', '西', '北', '中', '发', '白']
# 老头牌（1和9的数牌）
ROUTOU = ['一万', '九万', '一条', '九条', '一筒', '九筒']
# 字牌
JIHAI = ['东', '南', '西', '北', '中', '发', '白']
# 风牌
KAZEHAI = ['东', '南', '西', '北']
# 三元牌
SANGENPAI = ['中', '发', '白']
# 绿一色牌
GREEN_TILES = ['二条', '三条', '四条', '六条', '八条', '发']

# 宝牌指示牌 -> 宝牌的映射
DORA_NEXT = {
    '一万': '二万', '二万': '三万', '三万': '四万', '四万': '五万', '五万': '六万',
    '六万': '七万', '七万': '八万', '八万': '九万', '九万': '一万',
    '一条': '二条', '二条': '三条', '三条': '四条', '四条': '五条', '五条': '六条',
    '六条': '七条', '七条': '八条', '八条': '九条', '九条': '一条',
    '一筒': '二筒', '二筒': '三筒', '三筒': '四筒', '四筒': '五筒', '五筒': '六筒',
    '六筒': '七筒', '七筒': '八筒', '八筒': '九筒', '九筒': '一筒',
    '东': '南', '南': '西', '西': '北', '北': '东',
    '中': '发', '发': '白', '白': '中',
    '赤五万': '六万', '赤五条': '六条', '赤五筒': '六筒',
}


def normalize_tile(tile):
    """将赤牌转换为普通牌（用于牌型判断）"""
    if tile == '赤五万':
        return '五万'
    if tile == '赤五条':
        return '五条'
    if tile == '赤五筒':
        return '五筒'
    return tile


def is_red_dora(tile):
    """是否是赤宝牌"""
    return tile in RED_DORA


def get_tile_suit(tile):
    """获取牌的花色: 'wan', 'tiao', 'tong', 'zi'"""
    tile = normalize_tile(tile)
    info = TILE_INFO.get(tile)
    return info[0] if info else None


def get_tile_number(tile):
    """获取牌的数字（1-9），字牌返回1-7"""
    tile = normalize_tile(tile)
    info = TILE_INFO.get(tile)
    return info[1] if info else None


def is_number_tile(tile):
    """是否是数牌（万条筒）"""
    suit = get_tile_suit(tile)
    return suit in ('wan', 'tiao', 'tong')


def is_honor_tile(tile):
    """是否是字牌"""
    return get_tile_suit(tile) == 'zi'


def is_terminal(tile):
    """是否是老头牌（1或9）"""
    return normalize_tile(tile) in ROUTOU


def is_yaojiu(tile):
    """是否是幺九牌（老头牌或字牌）"""
    return normalize_tile(tile) in YAOJIU


def get_tile_by_suit_number(suit, num):
    """根据花色和数字获取牌名"""
    if suit == 'wan':
        names = ['', '一万', '二万', '三万', '四万', '五万', '六万', '七万', '八万', '九万']
    elif suit == 'tiao':
        names = ['', '一条', '二条', '三条', '四条', '五条', '六条', '七条', '八条', '九条']
    elif suit == 'tong':
        names = ['', '一筒', '二筒', '三筒', '四筒', '五筒', '六筒', '七筒', '八筒', '九筒']
    else:
        return None
    return names[num] if 1 <= num <= 9 else None


class MahjongData:
    """麻将游戏数据"""
    
    def __init__(self):
        self.tiles = TILES
    
    def get_all_tiles(self, use_red_dora=True):
        """获取一副完整的麻将牌（每种4张，可选赤牌）"""
        all_tiles = []
        for tile_type in self.tiles.values():
            for tile in tile_type:
                if use_red_dora and tile in ('五万', '五条', '五筒'):
                    # 3张普通5 + 1张赤5
                    all_tiles.extend([tile] * 3)
                    red_tile = '赤' + tile
                    all_tiles.append(red_tile)
                else:
                    all_tiles.extend([tile] * 4)
        return all_tiles
    
    def get_dora(self, indicator_tile):
        """根据宝牌指示牌获取宝牌"""
        return DORA_NEXT.get(normalize_tile(indicator_tile), indicator_tile)

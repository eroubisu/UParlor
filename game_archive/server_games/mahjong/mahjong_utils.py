"""
麻将第三方库桥接层

将项目内部的中文牌名（如 '一万'、'赤五条'）与 mahjong 库的 136 编码互转，
并封装 HandCalculator / Shanten 的调用。
"""

from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from mahjong.meld import Meld as LibMeld
from mahjong.shanten import Shanten
from mahjong.tile import TilesConverter
from mahjong.constants import FIVE_RED_MAN, FIVE_RED_PIN, FIVE_RED_SOU

from .game_data import normalize_tile, is_red_dora, DORA_NEXT


# ── 牌名 ↔ 136 编码 映射 ──────────────────────────────

# 中文牌名 → (花色字母, 数字)   用于 TilesConverter
_TILE_TO_CODE = {
    '一万': ('man', '1'), '二万': ('man', '2'), '三万': ('man', '3'),
    '四万': ('man', '4'), '五万': ('man', '5'), '六万': ('man', '6'),
    '七万': ('man', '7'), '八万': ('man', '8'), '九万': ('man', '9'),
    '一条': ('sou', '1'), '二条': ('sou', '2'), '三条': ('sou', '3'),
    '四条': ('sou', '4'), '五条': ('sou', '5'), '六条': ('sou', '6'),
    '七条': ('sou', '7'), '八条': ('sou', '8'), '九条': ('sou', '9'),
    '一筒': ('pin', '1'), '二筒': ('pin', '2'), '三筒': ('pin', '3'),
    '四筒': ('pin', '4'), '五筒': ('pin', '5'), '六筒': ('pin', '6'),
    '七筒': ('pin', '7'), '八筒': ('pin', '8'), '九筒': ('pin', '9'),
    '东': ('honors', '1'), '南': ('honors', '2'),
    '西': ('honors', '3'), '北': ('honors', '4'),
    '白': ('honors', '5'), '发': ('honors', '6'), '中': ('honors', '7'),
}

# 赤牌 → 136 编码常量
_RED_DORA_MAP = {
    '赤五万': FIVE_RED_MAN,
    '赤五条': FIVE_RED_SOU,
    '赤五筒': FIVE_RED_PIN,
}

# 风 → 库常量
_WIND_MAP = {
    '东': TilesConverter.string_to_136_array(honors='1')[0],
    '南': TilesConverter.string_to_136_array(honors='2')[0],
    '西': TilesConverter.string_to_136_array(honors='3')[0],
    '北': TilesConverter.string_to_136_array(honors='4')[0],
}

# 34 编码 → 中文牌名（反查用）
_ALL_34_NAMES = [
    '一万', '二万', '三万', '四万', '五万', '六万', '七万', '八万', '九万',
    '一条', '二条', '三条', '四条', '五条', '六条', '七条', '八条', '九条',
    '一筒', '二筒', '三筒', '四筒', '五筒', '六筒', '七筒', '八筒', '九筒',
    '东', '南', '西', '北', '白', '发', '中',
]


# ── 全局实例 ──────────────────────────────────────────

_calculator = HandCalculator()
_shanten = Shanten()


# 每种牌的 136 编码池（每种 4 张），用于分配 tile_id
# 136 编码: 牌种 i 的 4 张牌 = i*4, i*4+1, i*4+2, i*4+3
def _tile_name_to_136(tile_name, used_ids=None):
    """将一张中文牌名转为 136 编码 ID，自动避免重复分配。

    Args:
        tile_name: 中文牌名如 '一万'、'赤五条'
        used_ids: set，已分配过的 136-ID 集合（调用方维护）

    Returns:
        int: 136 编码 ID
    """
    if used_ids is None:
        used_ids = set()

    # 赤宝牌有固定 ID
    if tile_name in _RED_DORA_MAP:
        tid = _RED_DORA_MAP[tile_name]
        used_ids.add(tid)
        return tid

    norm = normalize_tile(tile_name)
    code = _TILE_TO_CODE.get(norm)
    if code is None:
        raise ValueError(f"Unknown tile: {tile_name}")

    # 计算 34 编码索引，再展开为 4 个 136 候选
    suit, num_str = code
    base_id = TilesConverter.string_to_136_array(**{suit: num_str})[0]
    tile_34_idx = base_id // 4
    candidates = [tile_34_idx * 4 + i for i in range(4)]

    # 非赤牌的普通五万/五条/五筒必须跳过赤牌 ID
    red_ids = set(_RED_DORA_MAP.values())

    for tid in candidates:
        if tid not in used_ids and tid not in red_ids:
            used_ids.add(tid)
            return tid

    # 所有非赤 ID 都用完了，回退到任意可用
    for tid in candidates:
        if tid not in used_ids:
            used_ids.add(tid)
            return tid

    return candidates[0]


def tiles_to_136(tile_names):
    """批量转换中文牌名列表 → 136 编码列表"""
    used = set()
    return [_tile_name_to_136(t, used) for t in tile_names]


def tiles_to_34(tile_names):
    """中文牌名列表 → 34 编码数组（用于向听数计算）"""
    arr = [0] * 34
    for t in tile_names:
        norm = normalize_tile(t)
        code = _TILE_TO_CODE.get(norm)
        if code:
            suit, num_str = code
            idx = TilesConverter.string_to_136_array(**{suit: num_str})[0] // 4
            arr[idx] += 1
    return arr


def melds_to_lib(melds, used_ids):
    """将项目的副露格式转为库的 Meld 列表。

    Args:
        melds: [{'type': 'pong'/'kong'/'concealed_kong'/'chow', 'tiles': [...]}]
        used_ids: set，已分配的 136-ID 集合

    Returns:
        list[LibMeld]
    """
    lib_melds = []
    for m in melds:
        tiles_136 = [_tile_name_to_136(t, used_ids) for t in m.get('tiles', [])]
        mtype = m['type']
        if mtype == 'pong':
            lib_melds.append(LibMeld(meld_type=LibMeld.PON, tiles=tiles_136))
        elif mtype == 'kong':
            lib_melds.append(LibMeld(meld_type=LibMeld.KAN, tiles=tiles_136, opened=True))
        elif mtype == 'concealed_kong':
            lib_melds.append(LibMeld(meld_type=LibMeld.KAN, tiles=tiles_136, opened=False))
        elif mtype == 'chow':
            lib_melds.append(LibMeld(meld_type=LibMeld.CHI, tiles=sorted(tiles_136)))
    return lib_melds


# ── 公开 API ─────────────────────────────────────────

def calculate_shanten(hand_tiles, melds=None):
    """计算向听数。

    Args:
        hand_tiles: 中文牌名列表（闭手部分，不含副露牌）
        melds: 副露列表（可选，用于计算副露后的向听数）

    Returns:
        int: 向听数。0=听牌，-1=已和牌
    """
    tiles_34 = tiles_to_34(hand_tiles)
    # 副露牌也要算入 34 编码
    if melds:
        for m in melds:
            for t in m.get('tiles', []):
                norm = normalize_tile(t)
                code = _TILE_TO_CODE.get(norm)
                if code:
                    suit, num_str = code
                    idx = TilesConverter.string_to_136_array(**{suit: num_str})[0] // 4
                    tiles_34[idx] += 1
    return _shanten.calculate_shanten(tiles_34)


def can_win(hand_tiles, win_tile=None):
    """检查手牌是否能和牌（向听数 == -1）。

    Args:
        hand_tiles: 闭手牌列表。如果含 win_tile 则 14 张；否则 13 张 + win_tile
        win_tile: 和的那张牌（可选，会追加到 hand_tiles）

    Returns:
        bool
    """
    tiles = list(hand_tiles)
    if win_tile:
        tiles.append(win_tile)
    tiles_34 = tiles_to_34(tiles)
    return _shanten.calculate_shanten(tiles_34) == -1


def estimate_hand(hand_tiles, melds, win_tile, *,
                  is_tsumo=False, is_riichi=False, is_ippatsu=False,
                  is_rinshan=False, is_chankan=False,
                  is_haitei=False, is_houtei=False,
                  is_tenhou=False, is_chihou=False,
                  is_double_riichi=False,
                  player_wind=None, round_wind=None,
                  dora_indicators=None, ura_dora_indicators=None):
    """完整手牌计算：役种 + 符数 + 点数。

    Args:
        hand_tiles: 闭手牌（含 win_tile 的完整 14 张，不含副露牌）
        melds: 副露列表 [{'type': ..., 'tiles': [...]}]
        win_tile: 和牌
        其余为环境参数

    Returns:
        dict | None:
            成功: {
                'han': int, 'fu': int, 'cost': dict,
                'yaku': [(name, han_value, is_yakuman), ...],
                'error': None
            }
            失败: {'error': str}
    """
    used_ids = set()

    # 构建 136 编码
    hand_136 = [_tile_name_to_136(t, used_ids) for t in hand_tiles]
    lib_melds = melds_to_lib(melds, used_ids)

    # 副露牌加入 tiles（库要求 14 张总计）
    for m in melds:
        for t in m.get('tiles', []):
            hand_136.append(_tile_name_to_136(t, used_ids))

    # win_tile 必须指向 hand_136 中已有的 ID
    # 找到 hand_tiles 中最后一个匹配 win_tile 的 136 ID
    norm_win = normalize_tile(win_tile)
    is_red_win = is_red_dora(win_tile)
    win_136 = None
    for i in range(len(hand_tiles) - 1, -1, -1):
        if is_red_win:
            if hand_tiles[i] == win_tile:
                win_136 = hand_136[i]
                break
        else:
            if normalize_tile(hand_tiles[i]) == norm_win and not is_red_dora(hand_tiles[i]):
                win_136 = hand_136[i]
                break
    if win_136 is None:
        # fallback: 匹配任意 normalize 相同的
        for i in range(len(hand_tiles) - 1, -1, -1):
            if normalize_tile(hand_tiles[i]) == norm_win:
                win_136 = hand_136[i]
                break
    if win_136 is None:
        return {'error': 'win_tile_not_found'}

    # 构建 HandConfig
    config = HandConfig(
        is_tsumo=is_tsumo,
        is_riichi=is_riichi,
        is_ippatsu=is_ippatsu,
        is_rinshan=is_rinshan,
        is_chankan=is_chankan,
        is_haitei=is_haitei,
        is_houtei=is_houtei,
        is_tenhou=is_tenhou,
        is_chiihou=is_chihou,
        is_daburu_riichi=is_double_riichi,
        player_wind=_WIND_MAP.get(player_wind),
        round_wind=_WIND_MAP.get(round_wind),
        options=OptionalRules(
            has_aka_dora=True,
            has_open_tanyao=True,
        ),
    )

    # 宝牌指示牌 → 136 编码
    dora_136 = tiles_to_136(dora_indicators) if dora_indicators else None
    ura_136 = tiles_to_136(ura_dora_indicators) if ura_dora_indicators else None

    result = _calculator.estimate_hand_value(
        hand_136, win_136,
        melds=lib_melds or None,
        dora_indicators=dora_136,
        config=config,
    )

    if result.error:
        return {'error': result.error}

    # 如果有里宝牌且立直，再算一次含里宝
    # 库不直接支持 ura_dora，需要将 ura 也加入 dora_indicators
    if ura_136 and is_riichi:
        all_dora = (dora_136 or []) + ura_136
        result = _calculator.estimate_hand_value(
            hand_136, win_136,
            melds=lib_melds or None,
            dora_indicators=all_dora,
            config=config,
        )
        if result.error:
            return {'error': result.error}

    # 转换役种为项目格式
    yaku_list = []
    for y in result.yaku:
        name = _translate_yaku(y.name)
        is_yakuman = y.is_yakuman
        han_val = result.han if is_yakuman else y.han_closed if not lib_melds else y.han_open
        yaku_list.append((name, han_val, is_yakuman))

    return {
        'han': result.han,
        'fu': result.fu,
        'cost': result.cost,
        'yaku': yaku_list,
        'is_yakuman': any(y.is_yakuman for y in result.yaku),
        'error': None,
    }


# ── 役名翻译 ─────────────────────────────────────────

_YAKU_NAME_MAP = {
    'Menzen Tsumo': '门清自摸',
    'Riichi': '立直',
    'Ippatsu': '一发',
    'Chankan': '抢杠',
    'Rinshan Kaihou': '岭上开花',
    'Haitei Raoyue': '海底摸月',
    'Houtei Raoyui': '河底捞鱼',
    'Pinfu': '平和',
    'Tanyao': '断幺九',
    'Iipeiko': '一杯口',
    'Ton': '自风:东',
    'Nan': '自风:南',
    'Xia': '自风:西',
    'Pei': '自风:北',
    'Haku': '役牌:白',
    'Hatsu': '役牌:发',
    'Chun': '役牌:中',
    'Daburu Riichi': '双立直',
    'Chiitoitsu': '七对子',
    'Chanta': '混全带幺九',
    'Ittsu': '一气通贯',
    'San Shoku Doujun': '三色同顺',
    'San Shoku Doukou': '三色同刻',
    'Sankantsu': '三杠子',
    'Toitoi': '对对和',
    'Sanankou': '三暗刻',
    'Shousangen': '小三元',
    'Honroutou': '混老头',
    'Ryanpeikou': '二杯口',
    'Junchan': '纯全带幺九',
    'Honitsu': '混一色',
    'Chinitsu': '清一色',
    'Dora': '宝牌',
    'Aka Dora': '赤宝牌',
    'Tenhou': '天和',
    'Chiihou': '地和',
    'Daisangen': '大三元',
    'Suuankou': '四暗刻',
    'Suuankou Tanki': '四暗刻单骑',
    'Tsuuiisou': '字一色',
    'Ryuuiisou': '绿一色',
    'Chinroutou': '清老头',
    'Kokushi Musou': '国士无双',
    'Kokushi Musou Juusanmen Matchi': '国士无双十三面',
    'Shousuushii': '小四喜',
    'Daisuushii': '大四喜',
    'Chuuren Poutou': '九莲宝灯',
    'Daburu Chuuren Poutou': '纯正九莲宝灯',
    'Suukantsu': '四杠子',
    'Renhou': '人和',
    'Nagashi Mangan': '流局满贯',
    # 风牌役（库用位置编号）
    'Yakuhai (east)': '自风:东',
    'Yakuhai (south)': '自风:南',
    'Yakuhai (west)': '自风:西',
    'Yakuhai (north)': '自风:北',
    'Yakuhai (haku)': '役牌:白',
    'Yakuhai (hatsu)': '役牌:发',
    'Yakuhai (chun)': '役牌:中',
}


def _translate_yaku(name):
    """将库的英文役名翻译为中文"""
    return _YAKU_NAME_MAP.get(name, name)

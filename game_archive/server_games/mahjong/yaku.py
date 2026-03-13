"""
役种判定模块 - 日本麻将役种系统
通过 mahjong 库桥接层实现役种/符数/点数计算。
"""

from .mahjong_utils import estimate_hand


class YakuResult:
    """役种结果"""
    def __init__(self):
        self.yakus = []  # [(役名, 番数, 是否役满)]
        self.total_han = 0
        self.is_yakuman = False
        self.fu = 0
        self.cost = None  # 库返回的点数详情
    
    def add(self, name, han, is_yakuman=False):
        self.yakus.append((name, han, is_yakuman))
        if is_yakuman:
            self.is_yakuman = True
        else:
            self.total_han += han
    
    def get_display(self):
        """获取显示文本"""
        lines = []
        for name, han, is_ym in self.yakus:
            if is_ym:
                lines.append(f"🌟 {name} (役满)")
            else:
                lines.append(f"✓ {name} ({han}番)")
        return lines


def analyze_hand(hand_tiles, melds, win_tile, is_tsumo, is_riichi, is_ippatsu,
                 is_rinshan, is_chankan, is_haitei, is_houtei,
                 is_tenhou, is_chihou, is_double_riichi,
                 player_wind, round_wind,
                 dora_indicators=None, ura_dora_indicators=None,
                 # 以下为兼容旧调用方保留，不再使用
                 dora_count=0, ura_dora_count=0, red_dora_count=0):
    """
    分析手牌的役种（通过 mahjong 库桥接层）

    Returns:
        YakuResult（附带 fu / cost 属性）
    """
    bridge_result = estimate_hand(
        hand_tiles=hand_tiles,
        melds=melds,
        win_tile=win_tile,
        is_tsumo=is_tsumo,
        is_riichi=is_riichi,
        is_ippatsu=is_ippatsu,
        is_rinshan=is_rinshan,
        is_chankan=is_chankan,
        is_haitei=is_haitei,
        is_houtei=is_houtei,
        is_tenhou=is_tenhou,
        is_chihou=is_chihou,
        is_double_riichi=is_double_riichi,
        player_wind=player_wind,
        round_wind=round_wind,
        dora_indicators=dora_indicators,
        ura_dora_indicators=ura_dora_indicators,
    )

    result = YakuResult()

    if not bridge_result or bridge_result.get('error'):
        return result

    for name, han_val, is_ym in bridge_result['yaku']:
        result.add(name, han_val, is_ym)

    result.fu = bridge_result.get('fu', 0)
    result.cost = bridge_result.get('cost')
    result.is_yakuman = bridge_result.get('is_yakuman', False)
    if result.is_yakuman:
        result.total_han = 13

    return result


# ── 点数计算（纯算术，保留） ──────────────────────────

def calculate_score(han, fu, is_dealer, is_tsumo):
    """
    计算点数

    Args:
        han: 番数
        fu: 符数
        is_dealer: 是否庄家
        is_tsumo: 是否自摸

    Returns:
        dict: {'total': 总点数, 'from_dealer': 从庄家获得, 'from_non_dealer': 从闲家获得}
    """
    if han >= 13:
        base = 8000
    elif han >= 11:
        base = 6000
    elif han >= 8:
        base = 4000
    elif han >= 6:
        base = 3000
    elif han >= 5 or (han >= 4 and fu >= 40) or (han >= 3 and fu >= 70):
        base = 2000
    else:
        base = fu * (2 ** (han + 2))
        base = min(base, 2000)

    if is_dealer:
        if is_tsumo:
            each = _round_up_100(base * 2)
            return {'total': each * 3, 'from_non_dealer': each}
        else:
            total = _round_up_100(base * 6)
            return {'total': total}
    else:
        if is_tsumo:
            from_dealer = _round_up_100(base * 2)
            from_non_dealer = _round_up_100(base)
            return {
                'total': from_dealer + from_non_dealer * 2,
                'from_dealer': from_dealer,
                'from_non_dealer': from_non_dealer
            }
        else:
            total = _round_up_100(base * 4)
            return {'total': total}


def _round_up_100(n):
    """向上取整到100的倍数"""
    return ((n + 99) // 100) * 100

"""段位系统 — 段位查询、段位变化计算、游戏专属段位注册"""

from __future__ import annotations

from ..player.schema import RANKS, RANK_ORDER, _DEFAULT_RANK_TO_TITLE


# ══════════════════════════════════════════════════
#  注入注册表
# ══════════════════════════════════════════════════

_RANK_TO_TITLE: dict[str, str] = dict(_DEFAULT_RANK_TO_TITLE)   # {rank_id: title_id}
_GAME_RANKS: dict[str, dict] = {}       # {game_id: {'ranks': {...}, 'rank_order': [...]}}


# ══════════════════════════════════════════════════
#  注入接口（由 games/__init__.py::register_game 调用）
# ══════════════════════════════════════════════════

def register_rank_titles(mapping: dict) -> None:
    _RANK_TO_TITLE.update(mapping)


def register_game_ranks(game_id: str, ranks: dict, rank_order: list) -> None:
    """注入游戏专属段位体系（覆盖框架默认）"""
    _GAME_RANKS[game_id] = {'ranks': ranks, 'rank_order': rank_order}


# ══════════════════════════════════════════════════
#  段位查询（支持 game_type 切换段位体系）
# ══════════════════════════════════════════════════

def _get_ranks(game_type=None):
    if game_type and game_type in _GAME_RANKS:
        return _GAME_RANKS[game_type]['ranks']
    return RANKS


def get_rank_order(game_type=None):
    if game_type and game_type in _GAME_RANKS:
        return _GAME_RANKS[game_type]['rank_order']
    return RANK_ORDER


def get_rank_info(rank_id, game_type=None):
    ranks = _get_ranks(game_type)
    order = get_rank_order(game_type)
    return ranks.get(rank_id, ranks[order[0]])


def get_rank_name(rank_id, game_type=None):
    return get_rank_info(rank_id, game_type)['name']


def get_rank_index(rank_id, game_type=None):
    order = get_rank_order(game_type)
    try:
        return order.index(rank_id)
    except ValueError:
        return 0


def calculate_rank_change(current_rank, points_change, game_type=None):
    """计算段位变化。Returns: (new_rank, new_points, promoted, demoted)"""
    rank_info = get_rank_info(current_rank, game_type)
    rank_idx = get_rank_index(current_rank, game_type)
    order = get_rank_order(game_type)

    new_points = max(0, points_change)
    promoted = False
    demoted = False
    new_rank = current_rank

    if rank_info['points_up'] is not None and new_points >= rank_info['points_up']:
        if rank_idx < len(order) - 1:
            new_rank = order[rank_idx + 1]
            new_points = 0
            promoted = True
    elif rank_info['points_down'] is not None and new_points < rank_info['points_down']:
        if rank_idx > 0:
            prev_rank = order[rank_idx - 1]
            prev_tier = get_rank_info(prev_rank, game_type)['tier']
            current_tier = rank_info['tier']
            if current_tier > 2 or (current_tier == 2 and prev_tier == 2):
                new_rank = prev_rank
                new_points = get_rank_info(new_rank, game_type)['points_up'] // 2
                demoted = True

    return new_rank, new_points, promoted, demoted


def get_title_id_from_rank(rank_id):
    return _RANK_TO_TITLE.get(rank_id)

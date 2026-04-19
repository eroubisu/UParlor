"""段位系统 — 段位查询、段位变化计算、游戏专属段位注册"""

from __future__ import annotations

import json
import os

# ── 从 JSON 加载框架级段位数据 ──

_data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
with open(os.path.join(_data_dir, 'ranks.json'), 'r', encoding='utf-8') as _f:
    _ranks_data = json.load(_f)

RANKS = _ranks_data['ranks']
RANK_ORDER = _ranks_data['rank_order']
_DEFAULT_RANK_TO_TITLE = _ranks_data.get('rank_to_title', {})


# ── 注入注册表 ──

_RANK_TO_TITLE: dict[str, str] = dict(_DEFAULT_RANK_TO_TITLE)   # {rank_id: title_id}
_GAME_RANKS: dict[str, dict] = {}       # {game_id: {'ranks': {...}, 'rank_order': [...]}}


# ── 注入接口（由 games/__init__.py::register_game 调用） ──

def register_rank_titles(mapping: dict) -> None:
    _RANK_TO_TITLE.update(mapping)


def register_game_ranks(game_id: str, ranks: dict, rank_order: list) -> None:
    """注入游戏专属段位体系（覆盖框架默认）"""
    _GAME_RANKS[game_id] = {'ranks': ranks, 'rank_order': rank_order}


# ── 段位查询（支持 game_type 切换段位体系） ──

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


def get_title_id_from_rank(rank_id):
    return _RANK_TO_TITLE.get(rank_id)

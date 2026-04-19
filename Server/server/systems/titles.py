"""头衔系统 — 头衔查询、授予、游戏专属头衔注册"""

from __future__ import annotations

import json
import os

# ── 从 JSON 加载框架级头衔数据 ──

_data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
with open(os.path.join(_data_dir, 'titles.json'), 'r', encoding='utf-8') as _f:
    _titles_data = json.load(_f)

TITLE_LIBRARY = _titles_data['titles']
TITLE_SOURCES = _titles_data['sources']


# ── 注入接口（由 games/__init__.py::register_game 调用） ──

def register_game_titles(titles: dict) -> None:
    TITLE_LIBRARY.update(titles)


def register_game_title_sources(sources: dict) -> None:
    TITLE_SOURCES.update(sources)


# ── 头衔查询 ──

def get_title_info(title_id):
    return TITLE_LIBRARY.get(title_id)


def get_title_name(title_id):
    info = TITLE_LIBRARY.get(title_id)
    if info:
        return info['name']
    return title_id


def grant_title(player_data, title_id):
    from ..player.schema import default_titles
    titles = player_data.get('titles', default_titles())
    titles.setdefault('owned', [])
    if title_id not in titles['owned']:
        titles['owned'].append(title_id)
    player_data['titles'] = titles

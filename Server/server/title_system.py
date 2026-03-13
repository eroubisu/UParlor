"""头衔系统 — 头衔查询、授予、游戏专属头衔注册"""

from __future__ import annotations

from .user_schema import TITLE_LIBRARY, TITLE_SOURCES


# ══════════════════════════════════════════════════
#  注入接口（由 games/__init__.py::register_game 调用）
# ══════════════════════════════════════════════════

def register_game_titles(titles: dict) -> None:
    TITLE_LIBRARY.update(titles)


def register_game_title_sources(sources: dict) -> None:
    TITLE_SOURCES.update(sources)


# ══════════════════════════════════════════════════
#  头衔查询
# ══════════════════════════════════════════════════

def get_title_info(title_id):
    return TITLE_LIBRARY.get(title_id)


def get_title_name(title_id):
    info = TITLE_LIBRARY.get(title_id)
    if info:
        return info['name']
    return title_id


def get_titles_by_source(source):
    return {k: v for k, v in TITLE_LIBRARY.items() if v['source'] == source}


def get_all_title_names():
    return {info['name']: tid for tid, info in TITLE_LIBRARY.items()}


def grant_title(player_data, title_id):
    titles = player_data.get('titles', {'owned': ['newcomer'], 'displayed': ['newcomer']})
    titles.setdefault('owned', [])
    if title_id not in titles['owned']:
        titles['owned'].append(title_id)
    player_data['titles'] = titles

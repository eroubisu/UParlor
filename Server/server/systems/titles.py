"""头衔系统 — 头衔查询、授予、条件检查、游戏专属头衔注册"""

from __future__ import annotations

from datetime import datetime

from ..player.schema import TITLE_LIBRARY, TITLE_SOURCES


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


def get_titles_by_source(source):
    return {k: v for k, v in TITLE_LIBRARY.items() if v['source'] == source}


def get_all_title_names():
    return {info['name']: tid for tid, info in TITLE_LIBRARY.items()}


def grant_title(player_data, title_id):
    from ..player.schema import default_titles
    titles = player_data.get('titles', default_titles())
    titles.setdefault('owned', [])
    if title_id not in titles['owned']:
        titles['owned'].append(title_id)
    player_data['titles'] = titles


# ── 声明式条件检查（基于 titles.json 中的 check 字段） ──

def check_title_condition(title_id: str, player_data: dict) -> bool:
    """检查玩家是否满足某头衔的获取条件。

    根据 titles.json 中的 check 字段声明式判断：
      - auto: 注册即获得，始终 True
      - social_stats: 检查 social_stats 中某字段 >= 阈值
      - game_stats: 检查 game_stats 中某字段 >= 阈值
      - game_specific: 检查 player_data[game][stats][field] >= 阈值
      - created_before: 注册时间早于指定日期
      - login_between: 当前日期在指定范围内
    """
    info = TITLE_LIBRARY.get(title_id)
    if not info:
        return False
    check = info.get('check')
    if not check:
        return False

    check_type = check.get('type')

    if check_type == 'auto':
        return True

    elif check_type == 'social_stats':
        stats = player_data.get('social_stats', {})
        return stats.get(check['field'], 0) >= check.get('gte', 0)

    elif check_type == 'game_stats':
        stats = player_data.get('game_stats', {})
        return stats.get(check['field'], 0) >= check.get('gte', 0)

    elif check_type == 'game_specific':
        game = check.get('game', '')
        game_data = player_data.get(game, {})
        stats = game_data.get('stats', {})
        return stats.get(check['field'], 0) >= check.get('gte', 0)

    elif check_type == 'rank':
        from .ranks import get_rank_index
        from ..player.schema import _GAME_PLAYER_DEFAULTS
        target_rank = check.get('rank', '')
        target_idx = get_rank_index(target_rank)
        for game_id in _GAME_PLAYER_DEFAULTS:
            game_data = player_data.get(game_id, {})
            player_rank = game_data.get('rank', '')
            if player_rank and get_rank_index(player_rank, game_id) >= target_idx:
                return True
        return False

    elif check_type == 'created_before':
        created = player_data.get('created_at', '')
        if not created:
            return False
        return created < check['date']

    elif check_type == 'login_between':
        today = datetime.now().strftime('%Y-%m-%d')
        return check.get('start', '') <= today <= check.get('end', '')

    return False


def check_all_titles(player_data: dict) -> list[str]:
    """检查玩家满足条件但尚未拥有的所有头衔，返回新获得的 title_id 列表。"""
    owned = set(player_data.get('titles', {}).get('owned', []))
    newly_granted = []
    for title_id in TITLE_LIBRARY:
        if title_id not in owned and check_title_condition(title_id, player_data):
            grant_title(player_data, title_id)
            newly_granted.append(title_id)
    return newly_granted

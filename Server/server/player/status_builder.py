"""STATUS 消息构建 — 从 player_data 构建完整状态负载"""

from __future__ import annotations

from ..systems.titles import get_title_name
from .schema import (
    DEFAULT_CARD_FIELDS,
    DEFAULT_NAME_COLOR, DEFAULT_MOTTO_COLOR, DEFAULT_BORDER_COLOR,
)
from ..msg_types import STATUS


def build_status_message(server, player_data: dict) -> dict:
    """构建完整 STATUS 消息。"""
    titles_data = player_data.get('titles', {})
    displayed = titles_data.get('displayed', [])
    title_display = ' | '.join(get_title_name(t) for t in displayed) if displayed else ''
    from ..systems.leveling import exp_for_level
    status_data = {
        'name': player_data['name'],
        'level': player_data['level'],
        'exp': player_data.get('exp', 0),
        'exp_to_next': exp_for_level(player_data['level']),
        'gold': player_data['gold'],
        'title': title_display,
        'accessory': player_data.get('accessory'),
        'window_layout': player_data.get('window_layout'),
    }

    # 名片
    pc = player_data.get('profile_card', {})
    status_data['profile_card'] = {
        'motto': pc.get('motto', ''),
        'name_color': pc.get('name_color', DEFAULT_NAME_COLOR),
        'motto_color': pc.get('motto_color', DEFAULT_MOTTO_COLOR),
        'border_color': pc.get('border_color', DEFAULT_BORDER_COLOR),
        'card_fields': pc.get('card_fields', list(DEFAULT_CARD_FIELDS)),
    }
    status_data['created_at'] = player_data.get('created_at', '')
    status_data['friends_count'] = len(player_data.get('friends', []))

    # 游戏统计
    player_name = player_data.get('name', '')
    location = server.lobby_engine.get_player_location(player_name)
    game_id = server.lobby_engine._get_game_for_location(location)
    extras = {}
    if game_id:
        engine = server.lobby_engine._get_engine(game_id, player_name)
        if engine:
            extras = engine.get_status_extras(player_name, player_data) or {}
            # 注入当前游戏的段位信息
            rank_info = _build_rank_info(engine, player_data)
            if rank_info:
                status_data['game_rank'] = rank_info

    status_msg = {'type': STATUS, 'data': status_data}
    status_msg['location'] = location
    status_msg['location_path'] = server.lobby_engine.get_location_path(location, player_name)
    status_msg.update(extras)
    return status_msg


def _build_rank_info(engine, player_data: dict) -> dict | None:
    """构建当前游戏的段位信息供客户端状态面板显示"""
    from ..systems.ranks import get_rank_info, get_rank_order
    gk = getattr(engine, 'game_key', '')
    if not gk:
        return None
    rank_order = get_rank_order(gk)
    if not rank_order:
        return None
    default_rank = rank_order[0]
    gd = player_data.get(gk, {})
    rank_id = gd.get('rank', default_rank)
    rank_pts = gd.get('rank_points', 0)
    max_rank = gd.get('max_rank', default_rank)
    info = get_rank_info(rank_id, gk)
    max_info = get_rank_info(max_rank, gk)
    return {
        'game': getattr(engine, 'display_name', gk),
        'rank_name': info.get('name', '?'),
        'rank_points': rank_pts,
        'points_up': info.get('points_up'),
        'max_rank_name': max_info.get('name', '?'),
    }

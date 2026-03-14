"""物品系统 — 物品查询、游戏专属物品注册"""

from __future__ import annotations

from ..player.schema import ITEM_LIBRARY, ITEM_SOURCES


# ══════════════════════════════════════════════════
#  注入接口（由 games/__init__.py::register_game 调用）
# ══════════════════════════════════════════════════

def register_game_items(items: dict) -> None:
    ITEM_LIBRARY.update(items)


def register_game_item_sources(sources: dict) -> None:
    ITEM_SOURCES.update(sources)


# ══════════════════════════════════════════════════
#  物品查询
# ══════════════════════════════════════════════════

def get_item_info(item_id):
    return ITEM_LIBRARY.get(item_id)


def get_item_name(item_id):
    info = ITEM_LIBRARY.get(item_id)
    if info:
        return info['name']
    return item_id

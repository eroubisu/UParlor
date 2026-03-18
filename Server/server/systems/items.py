"""物品系统 — 物品查询、品质、库存操作、游戏专属物品注册"""

from __future__ import annotations

from ..player.schema import ITEM_LIBRARY, ITEM_SOURCES, QUALITY_MULTIPLIERS


# ══════════════════════════════════════════════════
#  品质系统
# ══════════════════════════════════════════════════

def quality_mult(quality: int) -> float:
    return QUALITY_MULTIPLIERS.get(str(quality), 1.0)


# ══════════════════════════════════════════════════
#  游戏级物品使用处理器注册
#  优先级: 游戏级 handler > 全局 handler > 声明式效果引擎
# ══════════════════════════════════════════════════

# {game_id: {item_id: handler}}
_GAME_USE_HANDLERS: dict[str, dict[str, callable]] = {}


def register_game_use_handler(game_id: str, item_id: str, handler) -> None:
    """注册游戏专属物品使用处理器"""
    _GAME_USE_HANDLERS.setdefault(game_id, {})[item_id] = handler


def get_game_use_handler(game_id: str | None, item_id: str):
    """查找游戏级处理器，无则返回 None"""
    if game_id:
        return _GAME_USE_HANDLERS.get(game_id, {}).get(item_id)
    return None


# ══════════════════════════════════════════════════
#  库存操作 — 支持品质分层存储
#  格式: inventory = {item_id: {str(quality): count, ...}}
#  兼容旧格式: {item_id: int} 视为 quality 0
# ══════════════════════════════════════════════════

def inv_get(inventory: dict, item_id: str, quality: int = 0) -> int:
    val = inventory.get(item_id, {})
    if isinstance(val, int):
        return val if quality == 0 else 0
    return val.get(str(quality), 0)


def inv_add(inventory: dict, item_id: str, quality: int = 0, count: int = 1):
    val = inventory.get(item_id, {})
    if isinstance(val, int):
        val = {"0": val}
        inventory[item_id] = val
    q_str = str(quality)
    val[q_str] = val.get(q_str, 0) + count
    inventory[item_id] = val


def inv_sub(inventory: dict, item_id: str, quality: int = 0, count: int = 1):
    val = inventory.get(item_id, {})
    if isinstance(val, int):
        val = {"0": val}
        inventory[item_id] = val
    q_str = str(quality)
    cur = val.get(q_str, 0)
    val[q_str] = max(0, cur - count)
    if val[q_str] <= 0:
        val.pop(q_str, None)
    if not val:
        inventory.pop(item_id, None)


def inv_total(inventory: dict, item_id: str) -> int:
    """某物品所有品质的总数"""
    val = inventory.get(item_id, {})
    if isinstance(val, int):
        return val
    return sum(v for v in val.values() if isinstance(v, int))


def parse_item_key(key: str) -> tuple[str, int]:
    """解析 'item_id:quality' → (item_id, quality)"""
    if ':' in key:
        parts = key.rsplit(':', 1)
        try:
            return parts[0], int(parts[1])
        except ValueError:
            return key, 0
    return key, 0


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

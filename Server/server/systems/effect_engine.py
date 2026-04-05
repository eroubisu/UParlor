"""声明式效果引擎 — 根据 items.json 中的 effect 字段自动执行通用效果

已注册效果类型:
  - add_exp      : 加经验（受品质倍率影响）
  - add_gold     : 加金币（受品质倍率影响）
  - heal_hp      : 恢复 HP（受品质倍率影响）
  - heal_mp      : 恢复 MP（受品质倍率影响）
  - random_gold  : 随机金币区间（受品质倍率影响）

当 items.json 中物品有 effect.type 字段且类型匹配，自动执行效果。
游戏模块可注册自定义效果类型。

handler 签名: (player_data, effect_cfg, quality) -> str (结果消息)
"""

from __future__ import annotations

from .items import quality_mult

# 效果处理器注册表: {type_name: handler}
_EFFECT_HANDLERS: dict[str, callable] = {}


def register_effect(effect_type: str, handler) -> None:
    """注册效果处理器"""
    _EFFECT_HANDLERS[effect_type] = handler


def process_effect(player_data: dict, effect_cfg: dict, quality: int = 0) -> str | None:
    """执行 effect，返回结果消息或 None（无匹配处理器）"""
    effect_type = effect_cfg.get('type')
    if not effect_type:
        return None
    handler = _EFFECT_HANDLERS.get(effect_type)
    if handler:
        return handler(player_data, effect_cfg, quality)
    return None


# ── 内置效果处理器 ──

def _effect_add_exp(player_data: dict, cfg: dict, quality: int) -> str:
    from .leveling import check_level_up
    base = cfg.get('value', 0)
    value = int(base * quality_mult(quality))
    player_data['exp'] = player_data.get('exp', 0) + value
    msg = f"获得 {value} 点经验值！"
    leveled = check_level_up(player_data)
    if leveled:
        msg += f"\n升级了！当前等级: {leveled[-1]}"
    return msg


def _effect_add_gold(player_data: dict, cfg: dict, quality: int) -> str:
    base = cfg.get('value', 0)
    value = int(base * quality_mult(quality))
    player_data['gold'] = player_data.get('gold', 0) + value
    return f"获得 {value} 金币！"


def _effect_heal_hp(player_data: dict, cfg: dict, quality: int) -> str:
    from .attributes import heal_hp
    base = cfg.get('value', 0)
    value = int(base * quality_mult(quality))
    actual = heal_hp(player_data, value)
    return f"恢复了 {actual} 点 HP！"


def _effect_heal_mp(player_data: dict, cfg: dict, quality: int) -> str:
    from .attributes import heal_mp
    base = cfg.get('value', 0)
    value = int(base * quality_mult(quality))
    actual = heal_mp(player_data, value)
    return f"恢复了 {actual} 点 MP！"


def _effect_random_gold(player_data: dict, cfg: dict, quality: int) -> str:
    import random
    mult = quality_mult(quality)
    gold_min = int(cfg.get('min', 1) * mult)
    gold_max = int(cfg.get('max', 10) * mult)
    amount = random.randint(gold_min, gold_max)
    player_data['gold'] = player_data.get('gold', 0) + amount
    return f"获得 {amount} 金币！"


register_effect('add_exp', _effect_add_exp)
register_effect('add_gold', _effect_add_gold)
register_effect('heal_hp', _effect_heal_hp)
register_effect('heal_mp', _effect_heal_mp)
register_effect('random_gold', _effect_random_gold)

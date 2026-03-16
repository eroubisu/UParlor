"""等级系统 — 经验曲线 & 升级检查"""

from __future__ import annotations

import json
from pathlib import Path

_CFG_PATH = Path(__file__).resolve().parent.parent / "data" / "levels.json"
_cfg: dict = {}


def _load_cfg() -> dict:
    global _cfg
    if not _cfg:
        with open(_CFG_PATH, encoding="utf-8") as f:
            _cfg = json.load(f)
    return _cfg


def max_level() -> int:
    return _load_cfg().get("max_level", 90)


def exp_for_level(level: int) -> int:
    """升到 level+1 所需经验，满级返回 0"""
    table = _load_cfg().get("exp_table", [])
    idx = level - 1
    if idx < 0 or idx >= len(table):
        return 0
    return table[idx]


def check_level_up(player_data: dict) -> list[int]:
    """检查并执行升级，返回升到的新等级列表（可能连升多级）"""
    level = player_data.get("level", 1)
    exp = player_data.get("exp", 0)
    cap = max_level()
    leveled = []

    while level < cap:
        needed = exp_for_level(level)
        if needed <= 0 or exp < needed:
            break
        exp -= needed
        level += 1
        leveled.append(level)

    player_data["level"] = level
    player_data["exp"] = exp
    return leveled

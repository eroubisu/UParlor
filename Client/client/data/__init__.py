"""客户端静态 UI 数据 — 从 JSON 加载"""

import json
import os

_dir = os.path.dirname(__file__)

with open(os.path.join(_dir, 'ui.json'), 'r', encoding='utf-8') as _f:
    _UI = json.load(_f)

# ── 品质显示 ──
QUALITY_LABELS: dict[str, str] = _UI['quality']['labels']
QUALITY_MARKERS: dict[int, tuple[str, str]] = {
    int(k): tuple(v) for k, v in _UI['quality']['markers'].items()
}

# ── 名片颜色预设 ──
COLOR_PRESETS: list[tuple[str, str]] = [tuple(p) for p in _UI['color_presets']]

# ── 名片字段定义 ──
CARD_FIELD_DEFS: list[tuple[str, str]] = [tuple(f) for f in _UI['card_fields']]

# ── 装备槽位标签 ──
EQUIPMENT_SLOT_LABELS: dict[str, str] = _UI.get('equipment_slots', {})

# ── 游戏状态配置 {game_type: {name, slots}} ──
GAME_STATUS_CONFIG: dict = _UI.get('game_status', {})

# ── 属性标签 ──
ATTRIBUTE_LABELS: dict[str, str] = _UI.get('attribute_labels', {})

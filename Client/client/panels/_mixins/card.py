"""名片渲染器 — 在 RichLog 中绘制带花色填充的居中名片框

供 StatusPanel（自己名片）和 OnlineUsersPanel（他人名片）共用。
"""

from __future__ import annotations

from rich.text import Text as RichText
from rich.cells import cell_len

from ...config import COLOR_FG_SECONDARY, COLOR_FG_TERTIARY, COLOR_BORDER_LIGHT
from ...data import CARD_FIELD_DEFS


# ── 默认花色 ──
_DEFAULT_PATTERN = {'chars': '.:+*~', 'colors': ['#606060', '#505050', '#707070']}

# ── 名片框样式 ──
_BORDER_COLOR = COLOR_BORDER_LIGHT
_FIELD_LABEL_COLOR = COLOR_FG_TERTIARY
_FIELD_VALUE_COLOR = COLOR_FG_SECONDARY

_CARD_MIN_WIDTH = 16
_CARD_MAX_WIDTH = 24

DEFAULT_CARD_FIELDS = ['level', 'gold', 'games', 'created']


def _make_pattern_text(width: int, pattern: dict, offset: int = 0) -> RichText:
    """生成指定宽度的花色填充 Text"""
    chars = pattern.get('chars', '.')
    colors = pattern.get('colors', ['#505050'])
    if not chars:
        chars = '.'
    if not colors:
        colors = ['#505050']
    t = RichText()
    for i in range(width):
        idx = (i + offset) % len(chars)
        ch = chars[idx]
        color = colors[(i + offset) % len(colors)]
        t.append(ch, style=color)
    return t


def _center_text(content: RichText, width: int) -> RichText:
    """将 content 居中到 width 宽度（按显示列计算）"""
    cw = cell_len(content.plain)
    if cw >= width:
        return content
    left = (width - cw) // 2
    right = width - cw - left
    t = RichText()
    t.append(' ' * left)
    t.append_text(content)
    t.append(' ' * right)
    return t


def _make_card_line(content: RichText, inner_width: int, bc: str = _BORDER_COLOR, align: str = 'center') -> RichText:
    """构建一行卡片内容：│ content │"""
    t = RichText()
    t.append('│', style=bc)
    if align == 'left':
        t.append(' ')
        t.append_text(content)
        remaining = inner_width - 1 - cell_len(content.plain)
        if remaining > 0:
            t.append(' ' * remaining)
    else:
        centered = _center_text(content, inner_width)
        t.append_text(centered)
    t.append('│', style=bc)
    return t


def _make_separator(inner_width: int, bc: str = _BORDER_COLOR) -> RichText:
    """构建分隔线：│─────│"""
    t = RichText()
    t.append('│', style=bc)
    t.append('─' * inner_width, style=bc)
    t.append('│', style=bc)
    return t


def _make_justified_line(label_t: RichText, value_t: RichText, inner_width: int, bc: str = _BORDER_COLOR) -> RichText:
    """构建两端对齐行：│ label    value │"""
    t = RichText()
    t.append('│', style=bc)
    t.append(' ')
    t.append_text(label_t)
    lw = cell_len(label_t.plain)
    vw = cell_len(value_t.plain)
    gap = inner_width - 2 - lw - vw
    gap = max(gap, 1)
    t.append(' ' * gap)
    t.append_text(value_t)
    t.append(' ')
    t.append('│', style=bc)
    return t


def _format_date(iso_str: str) -> str:
    """将 ISO 日期格式化为 YYYY-MM-DD"""
    if not iso_str:
        return '?'
    return iso_str[:10]


def _format_winrate(stats: dict) -> str:
    """计算胜率字符串"""
    total = stats.get('total_games', 0)
    wins = stats.get('total_wins', 0)
    if total <= 0:
        return '暂无'
    rate = wins / total * 100
    return f'{wins}/{total} {rate:.0f}%'


def _get_field_value(key: str, card_data: dict) -> str:
    """根据字段 key 返回显示值"""
    if key == 'level':
        return f'Lv.{card_data.get("level", 1)}'
    elif key == 'gold':
        return f'{card_data.get("gold", 0)}G'
    elif key == 'friends':
        return str(card_data.get('friends_count', 0))
    elif key == 'games':
        return _format_winrate(card_data.get('game_stats', {}))
    elif key == 'days':
        return str(card_data.get('social_stats', {}).get('login_days', 0))
    elif key == 'created':
        return _format_date(card_data.get('created_at', ''))
    return '?'


def build_card_lines(card_data: dict, fields: list[str] | None = None) -> list[RichText]:
    """构建名片框的所有行（不含花色填充）

    返回的每行宽度相同（card_width）。
    fields: 要展示的字段 key 列表（最多 4 个）。
    """
    name = card_data.get('name', '?')
    title = card_data.get('title', '')
    motto = card_data.get('motto', '')
    name_color = card_data.get('name_color', '#ffffff')
    motto_color = card_data.get('motto_color', '#b3b3b3')
    bc = card_data.get('border_color', _BORDER_COLOR)

    if fields is None:
        fields = card_data.get('card_fields', DEFAULT_CARD_FIELDS)

    # 计算卡片宽度（考虑名字和字段内容）
    name_w = cell_len(name) + 4
    field_labels_map = dict(CARD_FIELD_DEFS)
    max_field_w = 0
    for fid in fields[:4]:
        lbl = field_labels_map.get(fid, fid)
        val = _get_field_value(fid, card_data)
        fw = cell_len(lbl) + cell_len(val) + 3  # padding + gap
        max_field_w = max(max_field_w, fw)
    inner_width = max(_CARD_MIN_WIDTH, min(_CARD_MAX_WIDTH, max(name_w + 4, max_field_w)))

    lines: list[RichText] = []

    # 顶部边框
    top = RichText()
    top.append('╭' + '─' * inner_width + '╮', style=bc)
    lines.append(top)

    # 空行
    lines.append(_make_card_line(RichText(), inner_width, bc))

    # 名字（左对齐）
    name_t = RichText()
    name_t.append(name, style=f'bold {name_color}')
    lines.append(_make_card_line(name_t, inner_width, bc, align='left'))

    # 称号
    if title:
        title_t = RichText()
        title_t.append(f'── {title} ──', style=_FIELD_LABEL_COLOR)
        lines.append(_make_card_line(title_t, inner_width, bc, align='left'))

    # 空行
    lines.append(_make_card_line(RichText(), inner_width, bc))

    # 签名
    if motto:
        m_t = RichText()
        m_t.append(f'"{motto}"', style=motto_color)
        lines.append(_make_card_line(m_t, inner_width, bc, align='left'))
        lines.append(_make_card_line(RichText(), inner_width, bc))

    # 分隔线
    lines.append(_make_separator(inner_width, bc))

    # 可选字段（两端对齐：标签左 值右）
    field_labels = dict(CARD_FIELD_DEFS)
    for fid in fields[:4]:
        label = field_labels.get(fid, fid)
        value = _get_field_value(fid, card_data)
        label_t = RichText(label, style=_FIELD_LABEL_COLOR)
        value_t = RichText(value, style=_FIELD_VALUE_COLOR)
        lines.append(_make_justified_line(label_t, value_t, inner_width, bc))

    # 空行
    lines.append(_make_card_line(RichText(), inner_width, bc))

    # 底部边框
    bottom = RichText()
    bottom.append('╰' + '─' * inner_width + '╯', style=bc)
    lines.append(bottom)

    return lines


def render_card(log, card_data: dict, avail_width: int, avail_height: int = 0):
    """在 RichLog 中渲染带花色填充的居中名片

    log: RichLog 实例
    card_data: 名片数据 dict
    avail_width: 可用宽度（字符列）
    avail_height: 未使用（保留兼容）
    """
    log.clear()
    pattern = card_data.get('pattern', _DEFAULT_PATTERN)

    fields = card_data.get('card_fields', DEFAULT_CARD_FIELDS)
    card_lines = build_card_lines(card_data, fields)
    if not card_lines:
        return

    # 卡片宽度从第一行推断
    card_width = cell_len(card_lines[0].plain)

    # 水平居中计算
    left_pad = max(0, (avail_width - card_width) // 2)
    right_pad = max(0, avail_width - card_width - left_pad)

    card_rows = len(card_lines)
    if avail_height > 0:
        remaining = avail_height - card_rows
        top_fill = max(1, remaining // 2)
        bottom_fill = max(1, remaining - top_fill)
    else:
        top_fill = 1
        bottom_fill = 1

    row_offset = 0

    # 上方花色填充
    for _ in range(top_fill):
        log.write(_make_pattern_text(avail_width, pattern, offset=row_offset))
        row_offset += avail_width

    # 卡片行（左花色 + 卡片 + 右花色）
    for line in card_lines:
        full = RichText()
        if left_pad > 0:
            full.append_text(_make_pattern_text(left_pad, pattern, offset=row_offset))
        full.append_text(line)
        if right_pad > 0:
            full.append_text(_make_pattern_text(right_pad, pattern,
                                                offset=row_offset + left_pad + card_width))
        log.write(full)
        row_offset += avail_width

    # 下方花色填充
    for _ in range(bottom_fill):
        log.write(_make_pattern_text(avail_width, pattern, offset=row_offset))
        row_offset += avail_width

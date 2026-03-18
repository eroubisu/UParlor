"""面板共用工具函数"""

from __future__ import annotations

from rich.cells import cell_len
from textual.widgets import Static

from ..config import (
    COLOR_ACCENT, COLOR_FG_PRIMARY, COLOR_FG_SECONDARY,
    COLOR_FG_TERTIARY, COLOR_HINT_TAB_ACTIVE, COLOR_HINT_TAB_DIM,
)


def _set_pane_subtitle(widget, text: str):
    """沿 DOM 向上找到 PaneWrapper 并设置 border_subtitle"""
    node = widget.parent
    while node is not None:
        if hasattr(node, 'pane_id'):
            node.border_subtitle = text
            return
        node = node.parent


_AVAIL_FALLBACK = 1


def _widget_width(widget, widget_id: str = "") -> int:
    """获取 widget 内容可用宽度，获取不到时返回 fallback。"""
    if widget_id:
        try:
            w = widget.query_one(f"#{widget_id}")
            scr = w.scrollable_content_region.width
            if scr > 0:
                return scr
        except Exception:
            pass
    try:
        scr = widget.scrollable_content_region.width
        if scr > 0:
            return scr
    except Exception:
        pass
    return _AVAIL_FALLBACK


def build_tab_overflow(
    tab_parts: list[tuple[str, int]],
    active_idx: int,
    avail: int,
    dim_color: str,
) -> str:
    """计算带 <> 溢出箭头的标签栏文本。

    tab_parts: [(markup, plain_width), ...]
    active_idx: 当前激活标签的索引
    avail: 可用宽度（字符数），可通过 _widget_width() 获取
    dim_color: Rich 颜色名，用于 < > 箭头
    """
    if not tab_parts:
        return ""
    total_width = sum(w for _, w in tab_parts) + len(tab_parts) - 1
    if total_width <= avail:
        return " ".join(p for p, _ in tab_parts)

    arrow_w = 2
    selected = [(active_idx, tab_parts[active_idx])]
    used = tab_parts[active_idx][1]
    lo, hi = active_idx - 1, active_idx + 1
    while True:
        grew = False
        if lo >= 0:
            cost = tab_parts[lo][1] + 1 + (arrow_w if lo > 0 else 0)
            if used + cost + (arrow_w if hi < len(tab_parts) else 0) <= avail:
                selected.insert(0, (lo, tab_parts[lo]))
                used += tab_parts[lo][1] + 1
                lo -= 1
                grew = True
        if hi < len(tab_parts):
            cost = tab_parts[hi][1] + 1 + (arrow_w if hi < len(tab_parts) - 1 else 0)
            if used + cost + (arrow_w if lo >= 0 else 0) <= avail:
                selected.append((hi, tab_parts[hi]))
                used += tab_parts[hi][1] + 1
                hi += 1
                grew = True
        if not grew:
            break

    result = ""
    if lo >= 0:
        result += f"[{dim_color}]< [/]"
    result += " ".join(p for _, (p, _) in selected)
    if hi < len(tab_parts):
        result += f" [{dim_color}]>[/]"
    return result


def build_tab_parts(
    tabs: list[str],
    labels: dict[str, str],
    active: str,
) -> tuple[list[tuple[str, int]], int]:
    """构建标准标签页 tab_parts 和 active_idx。

    返回 (tab_parts, active_idx)，可直接传入 build_tab_overflow。
    """
    parts: list[tuple[str, int]] = []
    active_idx = 0
    for i, key in enumerate(tabs):
        label = labels.get(key, key)
        if key == active:
            active_idx = i
            plain = f"● {label}"
            markup = f"[{COLOR_HINT_TAB_ACTIVE}]{plain}[/]"
        else:
            plain = f"  {label}"
            markup = f"  [{COLOR_HINT_TAB_DIM}]{label}[/]"
        parts.append((markup, cell_len(plain)))
    return parts, active_idx


def render_tab_header(
    widget,
    header_id: str,
    tabs: list[str],
    labels: dict[str, str],
    active: str,
) -> None:
    """标准标签页渲染 — 构建 tab_parts 并更新 header Static 控件。"""
    parts, active_idx = build_tab_parts(tabs, labels, active)
    avail = _widget_width(widget, header_id)
    line = build_tab_overflow(parts, active_idx, avail, COLOR_FG_TERTIARY)
    try:
        widget.query_one(f"#{header_id}", Static).update(line)
    except Exception:
        pass


def update_tab_header(
    widget,
    header_id: str,
    tab_parts: list[tuple[str, int]],
    active_idx: int,
) -> None:
    """自定义 tab_parts 的标签页更新 — 用于需要特殊标记的面板。"""
    avail = _widget_width(widget, header_id)
    line = build_tab_overflow(tab_parts, active_idx, avail, COLOR_FG_TERTIARY)
    try:
        widget.query_one(f"#{header_id}", Static).update(line)
    except Exception:
        pass


def render_action_menu(
    actions: list[tuple[str, str]],
    cursor: int,
    indent: str = "     ",
) -> list[str]:
    """生成操作菜单的 Rich markup 行列表。

    actions: [(action_id, label), ...]
    cursor: 当前选中索引
    indent: 行首缩进（默认5空格）
    返回 Rich markup 字符串列表，可 append 到内容或 log.write。
    """
    lines: list[str] = []
    for i, (_, label) in enumerate(actions):
        if i == cursor:
            lines.append(
                f"{indent}[{COLOR_ACCENT}]\u25cf[/] [bold {COLOR_FG_PRIMARY}]{label}[/]")
        else:
            lines.append(
                f"{indent}  [{COLOR_FG_SECONDARY}]{label}[/]")
    return lines

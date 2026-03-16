"""面板共用工具函数"""


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

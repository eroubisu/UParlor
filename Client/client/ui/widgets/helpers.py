"""面板共用工具函数"""


def _set_pane_subtitle(widget, text: str):
    """沿 DOM 向上找到 PaneWrapper 并设置 border_subtitle"""
    node = widget.parent
    while node is not None:
        if hasattr(node, 'pane_id'):
            node.border_subtitle = text
            return
        node = node.parent

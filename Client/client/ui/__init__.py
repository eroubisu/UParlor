"""
ui — 用户界面子包

导出核心 UI 组件供外部使用。
面板组件通过 ui.panels 访问。
"""

from .canvas import Canvas, PaneWrapper, EmptyPane
from .layout import (
    LayoutNode, PaneNode, SplitNode,
    get_default_layout, get_game_layout,
    serialize, deserialize,
    all_panes, find_pane, find_module_pane,
    split_pane, close_pane, navigate, next_pane_id, resize_pane,
)
from ..widgets import (
    RoundedScrollBarRender, InputBarMixin, InputBar,
)

# 导入 panels 触发 register_module 注册
from .. import panels  # noqa: F401

__all__ = [
    'Canvas', 'PaneWrapper', 'EmptyPane',
    'LayoutNode', 'PaneNode', 'SplitNode',
    'get_default_layout', 'get_game_layout',
    'serialize', 'deserialize',
    'all_panes', 'find_pane', 'find_module_pane',
    'split_pane', 'close_pane', 'navigate', 'next_pane_id', 'resize_pane',
    'RoundedScrollBarRender', 'InputBarMixin', 'InputBar',
]

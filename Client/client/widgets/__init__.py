"""
基础 UI 组件 — 面板共用的核心 Widget

导入 scrollbar 模块以触发全局 ScrollBar.renderer 替换。
"""

from .helpers import _set_pane_subtitle, render_action_menu
from .scrollbar import RoundedScrollBarRender  # noqa: F401 — 触发全局渲染器替换
from .scroller import VirtualScroller
from .prompt import InputBarMixin
from .input_bar import InputBar, InputTextArea
from .tab_menu import TabMenuBase
from .menu_nav import MenuNav, render_menu_lines

__all__ = [
    '_set_pane_subtitle',
    'render_action_menu',
    'RoundedScrollBarRender',
    'VirtualScroller',
    'InputBarMixin',
    'InputBar',
    'InputTextArea',
    'TabMenuBase',
    'MenuNav',
    'render_menu_lines',
]

"""WindowEngine — 通用 TUI 窗口引擎

设计目标:
- 零业务耦合：引擎不知道宿主有什么模式、状态、键位风格
- 元数据驱动：每个窗口用 WindowSpec 声明 (id/title/menu/group/preconditions/bind/lifecycle)
- 注册即生效：register_window(WindowClass) → compose / 菜单 / 路由全自动
- 可独立成包：本目录所有代码不依赖任何 UParlor 业务符号 (state/mode/login/vim/...)

宿主集成只需 3 步:
    1. 注册窗口类: register_window(ChatWindow)
    2. 在 Screen.compose() 中: yield from engine.compose_all()
    3. 调度: engine.open('chat-window') / engine.menu_items('root') / engine.close_top()

公开 API:
    WindowSpec, register_window, WindowEngine
"""

from .spec import WindowSpec
from .registry import WindowRegistry, register_window
from .engine import WindowEngine
from .overlay import OverlayStack
from .text import cell_width, fit_cells, grapheme_clusters, wrap_cells
from .primitives import (
    ConfirmMenu,
    Divider,
    EngineInput,
    InputSession,
    InputSpec,
    move_option_index,
    Option,
    ScrollPolicy,
    SelectList,
    SurfaceKind,
    SurfaceState,
)

__all__ = [
    "WindowSpec",
    "WindowRegistry",
    "register_window",
    "WindowEngine",
    "OverlayStack",
    "cell_width",
    "fit_cells",
    "grapheme_clusters",
    "wrap_cells",
    "Divider",
    "EngineInput",
    "Option",
    "SelectList",
    "ConfirmMenu",
    "InputSpec",
    "InputSession",
    "move_option_index",
    "ScrollPolicy",
    "SurfaceKind",
    "SurfaceState",
]

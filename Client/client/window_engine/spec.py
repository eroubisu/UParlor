"""WindowSpec — 窗口元数据声明

每个窗口类通过类属性 `spec` 声明此结构，引擎据此完成全部调度。

通用性约束:
- 所有 callable 接收 `(window_instance, context)` 或 `(context,)`，context 类型由宿主决定 (Any)
- 引擎不解释 context 内容，只把它原样传给 callable
- 宿主负责定义自己的 context 结构 (如 dataclass、Screen 实例、dict 等)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# 类型别名 (Python 3.10+ 兼容)
Predicate = Callable[[Any], bool]                    # (context) -> bool
Binder = Callable[[Any, Any], None]                  # (window, context) -> None
LifecycleHook = Callable[[Any, Any], None]           # (window, context) -> None
BlockedHook = Callable[[Any, "WindowSpec"], None]    # (context, spec) -> None


@dataclass(frozen=True)
class WindowSpec:
    """窗口声明 — 描述一个窗口的全部行为契约

    必需:
        id: DOM/查询 id (例如 "chat-window")

    菜单集成:
        menu: 是否显示在所属菜单中
        title: 菜单/标题显示文本
        group: 所属菜单组 (默认 "root")
        order: 同组内排序权重 (越小越靠前)

    生命周期:
          mode: "floating" (默认, 互斥工作窗)、"popup" (临时覆盖层)
              或 "primary" (独占主窗口)
        preconditions: 打开前的检查列表 — 任一返回 False 则拒绝打开
        bind: 打开前调用 (window, context) -> None, 用于注入业务数据
        on_open: show() 之后调用 (window, context) -> None, 用于副作用 (如清除徽章)
        on_close: hide() 之后调用 (window, context) -> None
        on_blocked: 被 preconditions 拒绝时调用 (context, spec) -> None
    """

    id: str
    title: str = ""
    menu: bool = False
    group: str = "root"
    order: int = 100
    mode: str = "floating"  # "floating" | "popup" | "primary"

    preconditions: tuple[Predicate, ...] = field(default_factory=tuple)
    bind: Optional[Binder] = None
    on_open: Optional[LifecycleHook] = None
    on_close: Optional[LifecycleHook] = None
    on_blocked: Optional[BlockedHook] = None

"""游戏客户端处理器注册表"""

from __future__ import annotations

from typing import Protocol, Callable, runtime_checkable

from .commands import CommandInfo  # noqa: F401 — re-export for backward compat


# ── 处理器上下文 ──

class GameHandlerContext:
    """处理器与大厅交互的受控接口（State-first）"""

    def __init__(self, state, get_module, set_timer=None,
                 ensure_panel=None, remove_panel=None):
        self._state = state
        self._get_module = get_module
        self._set_timer = set_timer
        self._ensure_panel = ensure_panel
        self._remove_panel = remove_panel

    @property
    def state(self):
        return self._state

    def _widget_call(self, module: str, method: str, *args, **kwargs):
        """安全调用 Widget 方法"""
        w = self._get_module(module)
        if w and hasattr(w, method):
            getattr(w, method)(*args, **kwargs)

    def cmd_add_line(self, text: str):
        """向指令面板追加一行（State + Widget）"""
        self._state.cmd.add_line(text)
        self._widget_call('cmd', 'add_message', text)

    def cmd_widget_add_line(self, text: str):
        """仅向指令面板 Widget 追加一行（不写 State，用于延时动画）"""
        self._widget_call('cmd', 'add_message', text)

    def set_timer(self, delay: float, callback: Callable):
        """设置延时回调（用于动画等）"""
        if self._set_timer:
            self._set_timer(delay, callback)

    def ensure_panel(self, module_name: str):
        """确保模块面板存在于布局中（不存在则自动添加）"""
        if self._ensure_panel:
            self._ensure_panel(module_name)

    def remove_panel(self, module_name: str):
        """从布局中移除模块面板"""
        if self._remove_panel:
            self._remove_panel(module_name)


# ── 处理器协议 ──

@runtime_checkable
class GameClientHandler(Protocol):
    """游戏客户端处理器协议"""

    game_type: str

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        """处理游戏特有事件。返回 True 表示已处理"""
        ...

    def on_enter_game(self, ctx: GameHandlerContext) -> None:
        """进入游戏时调用"""
        ...

    def on_leave_game(self, ctx: GameHandlerContext) -> None:
        """离开游戏时调用"""
        ...


# ── 全局注册表 ──

HANDLER_REGISTRY: dict[str, GameClientHandler] = {}


def register_handler(handler: GameClientHandler) -> None:
    """注册游戏客户端处理器"""
    HANDLER_REGISTRY[handler.game_type] = handler


def get_handler(game_type: str) -> GameClientHandler | None:
    """根据 game_type 获取处理器"""
    return HANDLER_REGISTRY.get(game_type)

"""游戏客户端处理器注册表"""

from __future__ import annotations

from typing import Protocol, Callable, runtime_checkable


# ── 处理器上下文 ──

class GameHandlerContext:
    """处理器与大厅交互的受控接口（State-first）"""

    def __init__(self, state, get_module, set_timer=None,
                 send_command=None):
        self._state = state
        self.get_module = get_module
        self._set_timer = set_timer
        self._send_command = send_command

    @property
    def state(self):
        return self._state

    def _widget_call(self, module: str, method: str, *args, **kwargs):
        """安全调用 Widget 方法"""
        w = self.get_module(module)
        if w and hasattr(w, method):
            getattr(w, method)(*args, **kwargs)

    def set_timer(self, delay: float, callback: Callable):
        """设置延时回调（用于动画等）"""
        if self._set_timer:
            return self._set_timer(delay, callback)

    def send_command(self, command: str):
        """发送指令到服务器"""
        if self._send_command:
            self._send_command(command)

    def show_select_menu(self, title: str, items: list[dict], empty_msg: str = ''):
        """在操作面板上显示选择菜单"""
        self._widget_call('room_controls', 'show_select_menu',
                          title=title, items=items, empty_msg=empty_msg)


# ── 处理器协议 ──

@runtime_checkable
class GameClientHandler(Protocol):
    """游戏客户端处理器协议

    可选方法（用 hasattr/getattr 检查）：
    - on_nav(direction, ctx) — 方向键导航
    - on_nav_cancel(ctx) — 取消导航（Esc）
    - on_room_update(room_data, ctx) — 房间数据更新时调用
    - get_input_prefix(room_data) -> str — 输入框前缀
    """

    game_type: str

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        """处理游戏特有事件。返回 True 表示已处理"""
        ...


# ── 全局注册表 ──

HANDLER_REGISTRY: dict[str, GameClientHandler] = {}


def register_handler(handler: GameClientHandler) -> None:
    """注册游戏客户端处理器"""
    HANDLER_REGISTRY[handler.game_type] = handler


def get_handler(game_type: str) -> GameClientHandler | None:
    """根据 game_type 获取处理器"""
    return HANDLER_REGISTRY.get(game_type)

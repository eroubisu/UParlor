"""客户端事件处理器模板 — 处理服务端推送的游戏事件"""

from __future__ import annotations

from ..protocol.handler import register_handler, GameHandlerContext


class GameClientHandler:
    """TODO: 游戏客户端处理器 — 替换类名"""

    game_type = 'TODO_game_id'  # 必须与服务端 GAME_INFO['id'] 一致

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        """处理游戏特有事件。返回 True 表示已处理。

        ctx 提供:
          ctx.state          — ModuleStateManager（读写 State）
          ctx.cmd_add_line() — 向指令面板写消息
          ctx.set_timer()    — 延时回调（动画用）
          ctx.ensure_panel() — 确保面板在布局中
        """
        if event == 'example':
            ctx.cmd_add_line(f"收到事件: {data}")
            return True
        return False

    def on_enter_game(self, ctx: GameHandlerContext) -> None:
        """进入游戏时调用"""
        pass

    def on_leave_game(self, ctx: GameHandlerContext) -> None:
        """离开游戏时调用"""
        pass


# 模块导入时自动注册
register_handler(GameClientHandler())

"""
象棋客户端处理器 — 提供指令列表和事件处理

象棋的事件处理较少（主要是 room_update），指令补全是重点。
"""

from __future__ import annotations

from ..game_handler import (
    GameClientHandler,
    GameHandlerContext,
    CommandInfo,
    register_handler,
)


class ChessHandler:
    """象棋游戏客户端处理器"""

    game_type = "chess"

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        return False

    def get_available_commands(self, location: str) -> list[CommandInfo]:
        cmds = []
        if location == "chess":
            cmds.append(CommandInfo("/create", "创建房间", "创建国际象棋房间"))
            cmds.append(CommandInfo("/rooms", "房间列表", "查看当前房间"))
            cmds.append(CommandInfo("/join", "加入房间", "/join <房间ID>"))
            cmds.append(CommandInfo("/rank", "段位", "查看段位详情"))
            cmds.append(CommandInfo("/stats", "战绩", "查看战绩统计"))
        elif location == "chess_room":
            cmds.append(CommandInfo("/start", "开始", "开始对局"))
            cmds.append(CommandInfo("/bot", "机器人", "添加机器人对手"))
            cmds.append(CommandInfo("/invite", "邀请", "/invite <玩家名>"))
            cmds.append(CommandInfo("/kick", "踢出", "/kick <玩家名>"))
        elif location == "chess_playing":
            cmds.append(CommandInfo("/m", "走棋", "/m <走法> 如 e4, Nf3, O-O"))
            cmds.append(CommandInfo("/moves", "合法走法", "显示所有合法走法"))
            cmds.append(CommandInfo("/board", "棋盘", "刷新棋盘显示"))
            cmds.append(CommandInfo("/history", "记录", "查看走棋历史"))
            cmds.append(CommandInfo("/draw", "求和", "提出和棋"))
            cmds.append(CommandInfo("/resign", "认输", "投降认输"))
        return cmds

    def on_enter_game(self, ctx: GameHandlerContext) -> None:
        pass

    def on_leave_game(self, ctx: GameHandlerContext) -> None:
        pass


register_handler(ChessHandler())

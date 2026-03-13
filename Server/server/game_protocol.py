"""
游戏引擎协议定义

定义游戏引擎标准接口和数据结构，使大厅框架无需知道具体游戏类型。

两种引擎类型(通过 GAME_INFO['per_player'] 区分):
- 房间制引擎(per_player=False): 共享实例，管理多个房间 (如 chess, mahjong)
- 玩家制引擎(per_player=True): 每个玩家独立实例 (如 jrpg)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable, Any


# ── 游戏引擎标准接口 ──

@runtime_checkable
class GameEngine(Protocol):
    """游戏引擎标准接口"""

    def handle_command(self, lobby: Any, player_name: str, player_data: dict,
                       cmd: str, args: str) -> Any:
        """处理游戏指令。Returns: 响应消息(str/dict)，None 表示未匹配"""
        ...

    def handle_disconnect(self, lobby: Any, player_name: str) -> list[dict]:
        """处理玩家断线。Returns: 需要发送的通知列表"""
        ...

    def handle_back(self, lobby: Any, player_name: str, player_data: dict) -> Any:
        """处理 /back 指令"""
        ...

    def handle_quit(self, lobby: Any, player_name: str, player_data: dict) -> Any:
        """处理 /home 指令"""
        ...

    def get_welcome_message(self, player_data: dict) -> dict:
        """获取进入游戏时的欢迎信息"""
        ...


class BaseGameEngine:
    """游戏引擎基类 — 提供可选方法的默认空实现。

    游戏引擎继承此类即可省去样板代码，
    框架调用方无需 hasattr 检查。
    """

    def get_commands(self, lobby: Any, location: str, player_name: str,
                     player_data: dict) -> list[dict] | None:
        """动态返回当前位置的游戏指令列表。返回 None 时 fallback 到 commands.json。"""
        return None

    def get_profile_extras(self, player_data: dict) -> str | None:
        """个人资料页面的附加行（如段位、胜率等）"""
        return None

    def get_status_extras(self, player_name: str, player_data: dict) -> dict | None:
        """状态消息附加字段"""
        return None

    def get_player_room(self, player_name: str) -> Any:
        """查询玩家所在房间"""
        return None

    def get_player_room_data(self, player_name: str) -> dict | None:
        """查询房间数据（用于 UI 更新）"""
        return None

    def leave_room(self, player_name: str) -> None:
        """离开房间"""
        pass


# ── 游戏事件数据结构 ──

@dataclass
class GameEvent:
    """游戏引擎产生的事件 — 统一的输出协议

    框架级类型(大厅直接处理): room_update / game / location_update / game_end
    游戏特有类型(透传 game_event 信封): 任意自定义，由客户端处理器解读
    """
    type: str
    data: dict = field(default_factory=dict)
    target: str = ""  # 空=广播房间, 玩家名=点对点

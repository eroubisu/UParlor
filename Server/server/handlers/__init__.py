"""网络子包 — 消息处理器注册表与分发

handler 模块通过 @register 装饰器自注册，chat_server 在启动时
import 各 handler 模块触发注册，dispatch_playing() 负责路由。

子模块:
  chat          — 聊天/私聊消息
  client_state  — 客户端状态消息（viewport/save_layout/delete_account 等）
  friends       — 好友操作
  profile       — 名片查看/更新
  status_builder — 构建 STATUS 消息
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..chat_server import ChatServer

# handler 签名: (server, client_socket, name, player_data, msg) -> None
_HANDLERS: dict[str, callable] = {}


def register(msg_type: str):
    """装饰器：注册消息处理器。"""
    def decorator(fn):
        _HANDLERS[msg_type] = fn
        return fn
    return decorator


def dispatch_playing(server: ChatServer, client_socket, name: str, player_data: dict, msg: dict):
    """分发 playing 状态的客户端消息。返回 True 表示已处理。"""
    msg_type = msg.get('type', 'command')
    handler = _HANDLERS.get(msg_type)
    if handler:
        handler(server, client_socket, name, player_data, msg)
        return True
    return False

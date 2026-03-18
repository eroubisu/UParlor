"""网络子包 — 连接管理与消息分发"""

from .connection import NetworkManager
from .dispatch import dispatch_server_message

__all__ = ['NetworkManager', 'dispatch_server_message']

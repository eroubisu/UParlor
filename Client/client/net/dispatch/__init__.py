"""
消息分发 — 处理服务端推送消息的路由逻辑

数据流：msg_dispatch → State → (listener) → Widget
本模块只写 State，不直接操作 Widget。
"""

from __future__ import annotations

from ..messages import parse_server_message

from .auth import HANDLERS as _AUTH, handle_version_check
from .chat import HANDLERS as _CHAT
from .game import HANDLERS as _GAME
from .social import HANDLERS as _SOCIAL
from .system import HANDLERS as _SYSTEM

# 合并所有子模块的路由表
_DISPATCH: dict = {}
for _table in (_AUTH, _CHAT, _GAME, _SOCIAL, _SYSTEM):
    _DISPATCH.update(_table)


def dispatch_server_message(app, screen, raw: dict) -> None:
    """将解析后的服务器消息路由到 State。

    Widget 通过 State listener 自动收到通知并渲染。
    只有少数不经过 State 的 UI 操作（如布局、位置指示器）仍直接操作 screen。
    """
    # 版本检查 — 连接后服务器下发最新客户端版本号
    if raw.get('type') == 'client_version':
        handle_version_check(app, screen, raw.get('latest', ''))
        return

    parsed = parse_server_message(raw)
    handler = _DISPATCH.get(type(parsed))
    if handler:
        handler(parsed, app, screen, screen.state)

"""共享工具 — handler context 构建、markup 清理"""

from __future__ import annotations

import re as _re

from ...protocol.handler import GameHandlerContext, get_handler


def make_handler_ctx(st, app, screen) -> GameHandlerContext:
    return GameHandlerContext(
        state=st,
        get_module=screen.get_module,
        set_timer=app.set_timer,
        send_command=app.send_command,
    )


def strip_markup(text: str) -> str:
    """去除 Rich markup 标签，返回纯文本"""
    return _re.sub(r'\[/?[^\]]*\]', '', text)

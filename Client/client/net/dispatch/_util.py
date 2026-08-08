"""共享工具 — handler context 构建"""

from __future__ import annotations

from ...protocol.handler import GameHandlerContext


def make_handler_ctx(st, app, screen) -> GameHandlerContext:
    return GameHandlerContext(
        state=st,
        get_module=screen.get_module,
        set_timer=app.set_timer,
        send_command=app.send_command,
    )

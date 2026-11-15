"""玩家所在操作系统的唯一检测入口。

凡是和操作系统有关的客户端行为（输入法切换、TCP keepalive……）都先问这里，
再各自选后端；不要在别处直接读 ``sys.platform`` / ``platform.system()``。
没有适配的系统（``OTHER``）一律降级成"什么都不做"，不能报错。
"""

from __future__ import annotations

import sys

WINDOWS = "windows"
MACOS = "macos"
LINUX = "linux"
OTHER = "other"


def current() -> str:
    """当前系统：``WINDOWS`` / ``MACOS`` / ``LINUX`` / ``OTHER``。"""
    if sys.platform == "win32":
        return WINDOWS
    if sys.platform == "darwin":
        return MACOS
    if sys.platform.startswith("linux"):
        return LINUX
    return OTHER

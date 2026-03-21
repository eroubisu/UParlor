"""客户端配置"""

try:
    from importlib.metadata import version as _pkg_version
    VERSION = _pkg_version("uparlor")
except Exception:
    VERSION = None

import os as _os
from pathlib import Path as _Path

# 网络配置
PORT = 5555

def _read_default_host() -> str:
    env = _os.environ.get("UPARLOR_HOST")
    if env:
        return env
    host_file = _Path(__file__).resolve().parent.parent / 'host.txt'
    if host_file.is_file():
        return host_file.read_text(encoding='utf-8').strip()
    return '127.0.0.1'

DEFAULT_HOST = _read_default_host()

# Win11 风格配色
# 背景色（透明继承终端背景）
COLOR_BG_PRIMARY = 'transparent'
COLOR_BG_SECONDARY = 'transparent'
COLOR_BG_TERTIARY = 'transparent'
COLOR_BG_HOVER = 'transparent'

# 前景色
COLOR_FG_PRIMARY = '#ffffff'      # 主文字
COLOR_FG_SECONDARY = '#b3b3b3'    # 次级文字
COLOR_FG_TERTIARY = '#808080'     # 三级文字

# 强调色（灰度）
COLOR_ACCENT = '#a0a0a0'          # 主强调色（中灰）
COLOR_ACCENT_HOVER = '#b8b8b8'    # 悬停强调（亮灰）
COLOR_ACCENT_LIGHT = '#d0d0d0'    # 浅强调色（浅灰）

# 边框色
COLOR_BORDER = '#454545'          # 边框
COLOR_BORDER_LIGHT = '#5a5a5a'    # 浅边框

# 功能色（灰度）
COLOR_SUCCESS = '#a0a0a0'         # 成功/在线
COLOR_WARNING = '#c0c0c0'         # 警告
COLOR_ERROR = '#707070'           # 错误

# 指令提示栏
COLOR_HINT_BORDER = '#a0a0a0'     # 指令提示框边框
COLOR_HINT_TAB_ACTIVE = '#a0a0a0' # 活动标签页
COLOR_HINT_TAB_DIM = '#606060'    # 非活动标签页

# 指令名称色（淡紫，用于帮助文本/提示中高亮指令名）
COLOR_CMD = '#b39ddb'

# ── Rich Markup 语义常量（全局统一，禁止硬编码 [dim]/[b] 等） ──
# 用法：f"{M_DIM}文本{M_END}", f"{M_BOLD}标题{M_END}"
M_DIM     = f'[{COLOR_FG_TERTIARY}]'       # 弱化文本（替代 [dim]）
M_BOLD    = f'[bold {COLOR_FG_PRIMARY}]'    # 加粗标题（替代 [b]）
M_ACCENT  = f'[{COLOR_ACCENT}]'             # 强调
M_MUTED   = f'[{COLOR_FG_SECONDARY}]'       # 次要文本
M_CMD     = f'[bold {COLOR_CMD}]'             # 指令名称（淡紫色）
M_END     = '[/]'                            # 关闭标记

# ── 面板行数限制 ──
MAX_LINES_CMD = 1000
MAX_LINES_CHAT = 500
MAX_LINES_STATUS = 500
MAX_LINES_ONLINE = 200

# ── 频道 ──
CHANNEL_NAMES = {1: "世界", 2: "房间"}



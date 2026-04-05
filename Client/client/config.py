"""客户端配置"""

import os

try:
    from importlib.metadata import version as _pkg_version
    VERSION = _pkg_version("uparlor")
except Exception:
    VERSION = None

# 网络配置
PORT = 5555
DEFAULT_HOST = os.environ.get('UPARLOR_HOST', '112.126.80.53')

# Win11 风格配色
# 前景色
COLOR_FG_PRIMARY = '#ffffff'      # 主文字
COLOR_FG_SECONDARY = '#b3b3b3'    # 次级文字
COLOR_FG_TERTIARY = '#808080'     # 三级文字

# 强调色（灰度）
COLOR_ACCENT = '#a0a0a0'          # 主强调色（中灰）

# 边框色
COLOR_BORDER = '#454545'          # 边框
COLOR_BORDER_LIGHT = '#5a5a5a'    # 浅边框

# 指令提示栏
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



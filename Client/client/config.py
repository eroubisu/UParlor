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

# 语义色（低饱和功能性彩色，仅用于属性值和状态指示）
COLOR_GOLD    = '#d4a017'   # 金币、货币
COLOR_LEVEL   = '#6fa8dc'   # 等级
COLOR_ONLINE  = '#81c784'   # 在线、成功
COLOR_OFFLINE = '#e57373'   # 离线、危险
COLOR_WARNING = '#ffb74d'   # 警告、高延迟
COLOR_EXP     = '#b39ddb'   # 经验值
COLOR_ITEM    = '#a1887f'   # 物品、消耗品
COLOR_SOCIAL  = '#90caf9'   # 好友、社交

# ── Rich Markup 语义常量（全局统一，禁止硬编码 [dim]/[b] 等） ──
# 用法：f"{M_DIM}文本{M_END}", f"{M_BOLD}标题{M_END}"
M_DIM     = f'[{COLOR_FG_TERTIARY}]'       # 弱化文本（替代 [dim]）
M_BOLD    = f'[bold {COLOR_FG_PRIMARY}]'    # 加粗标题（替代 [b]）
M_ACCENT  = f'[{COLOR_ACCENT}]'             # 强调
M_MUTED   = f'[{COLOR_FG_SECONDARY}]'       # 次要文本
M_CMD     = f'[bold {COLOR_CMD}]'             # 指令名称（淡紫色）
M_GOLD    = f'[{COLOR_GOLD}]'               # 金币
M_LEVEL   = f'[{COLOR_LEVEL}]'              # 等级
M_ONLINE  = f'[{COLOR_ONLINE}]'             # 在线
M_OFFLINE = f'[{COLOR_OFFLINE}]'            # 离线
M_EXP     = f'[{COLOR_EXP}]'               # 经验
M_ITEM    = f'[{COLOR_ITEM}]'              # 物品
M_SOCIAL  = f'[{COLOR_SOCIAL}]'             # 社交
M_END     = '[/]'                            # 关闭标记

# ── Nerd Font 图标（私有区字符，需终端安装 Nerd Font） ──
NF_COIN     = '\uf155'   #  美元符
NF_LEVEL    = '\uf0e7'   #  闪电
NF_STAR     = '\uf005'   #  星
NF_USER     = '\uf007'   #  用户
NF_USERS    = '\uf0c0'   #  多人
NF_ONLINE   = '\uf111'   #  实心圆
NF_OFFLINE  = '\uf10c'   #  空心圆
NF_SWORD    = '\uf0e7'   #  闪电/对战
NF_BELL     = '\uf0f3'   #  铃铛
NF_HEART    = '\uf004'   #  爱心
NF_CALENDAR = '\uf073'   #  日历
NF_BAG      = '\uf290'   #  背包
NF_SEARCH   = '\uf002'   #  搜索
NF_GEAR     = '\uf013'   #  齿轮
NF_HOME     = '\uf015'   #  主页
NF_CMD      = '\uf120'   #  终端
NF_TROPHY   = '\uf091'   #  奖杯
NF_CHECK    = '\uf00c'   #  对勾
NF_CROSS    = '\uf00d'   #  叉
NF_ARROW_R  = '\uf061'   #  右箭头
NF_KEY      = '\uf084'   #  钥匙
NF_CARDS    = '\uf24d'   #  叠牌（clone）

# ── 面板行数限制 ──
MAX_LINES_CMD = 1000
MAX_LINES_CHAT = 500

# ── 图标对齐缩进（icon_align 面板中无图标行的前缀） ──
ICON_INDENT = '  '  # 2 空格 = 光标符号(1) + 空格(1)，光标符号必须为 ASCII




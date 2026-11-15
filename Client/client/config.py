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
COLOR_HINT_TAB_DIM = '#606060'    # 非活动标签页

# 指令名称色（淡紫，用于帮助文本/提示中高亮指令名）
COLOR_CMD = '#b39ddb'

# 语义色（低饱和功能性彩色，仅用于属性值和状态指示）
COLOR_ONLINE  = '#81c784'   # 在线、成功
COLOR_OFFLINE = '#e57373'   # 离线、危险
COLOR_WARNING = '#ffb74d'   # 警告、高延迟

# 游戏专用语义色：游戏模块只准用这里的名字，不要在 games/ 里写十六进制
COLOR_GAME_HEAD    = '#e0e0e0'   # 游戏面板小标题
COLOR_GAME_TEXT    = '#c0c0c0'   # 游戏正文
COLOR_GAME_MARK    = '#e0c040'   # 高亮标记（建议按钮、预测落点、强调棋子）
COLOR_GAME_BALL    = '#e06060'   # 球
COLOR_GAME_FIELDER = '#50b070'   # 野手 / 己方棋子
COLOR_GAME_RUNNER  = '#c080f0'   # 跑者
COLOR_GAME_WALL    = '#909090'   # 场地边界（本垒打墙）
COLOR_GAME_READY   = '#50b070'   # 已交牌（绿灯）：和野手同一个绿
COLOR_GAME_HIT     = '#e0c040'   # 击出方向标记（高飞/平飞/滚地）

# ── Rich Markup 语义常量（全局统一，禁止硬编码 [dim]/[b] 等） ──
# 用法：f"{M_DIM}文本{M_END}", f"{M_BOLD}标题{M_END}"
M_DIM     = f'[{COLOR_FG_TERTIARY}]'       # 弱化文本（替代 [dim]）
M_BOLD    = f'[bold {COLOR_FG_PRIMARY}]'    # 加粗标题（替代 [b]）
M_MUTED   = f'[{COLOR_FG_SECONDARY}]'       # 次要文本
M_CMD     = f'[bold {COLOR_CMD}]'             # 指令名称（淡紫色）
M_ONLINE  = f'[{COLOR_ONLINE}]'             # 在线
M_OFFLINE = f'[{COLOR_OFFLINE}]'            # 离线
M_END     = '[/]'                            # 关闭标记

# ── Nerd Fonts v3 图标（私有区字符，需使用 Nerd Font Mono） ──
NERD_FONT_BASELINE = "3"

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
NF_COMMENT  = '\uf075'   #  对话
NF_COMPANION = '\uf1b0'  #  旅伴（爪印）
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
NF_ARROW_L  = '\uf060'   #  左箭头
NF_ARROW_U  = '\uf062'   #  上箭头
NF_ARROW_D  = '\uf063'   #  下箭头
NF_KEY      = '\uf084'   #  钥匙
NF_CARDS    = '\uf24d'   #  叠牌（clone）
NF_PLANE    = '\uf072'   #  飞机
NF_WARNING  = '\uf071'   #  警告
NF_SUN      = '\uf185'   #  太阳
NF_MOON     = '\uf186'   #  月亮
NF_BAN      = '\uf05e'   #  禁止
NF_EXCHANGE = '\uf0ec'   #  交换
NF_REPEAT   = '\uf01e'   #  循环
NF_CARET_U  = '\uf0d8'   #  上三角
NF_CARET_D  = '\uf0d7'   #  下三角
NF_DIAMOND  = '\uf219'   #  菱形
NF_BULLSEYE = '\uf140'   #  靶心
NF_FLAG      = '\uf024'   #  旗帜
NF_CIRCLE_NOTCH = '\uf1ce'  #  虚线圈（预测落点）
# 击出方向（投打行左端＝本垒上的结果符号）：Octicons 斜箭头，验过在 Nerd Font 里存在
NF_HIT_HIGH = '\uf46c'      #  右上箭头（高飞 / 全垒打）
NF_HIT_FLAT = '\uf432'      #  右箭头（平飞）
NF_HIT_LOW  = '\uf43e'      #  右下箭头（滚地）

# Powerlevel10k-compatible chat title glyphs. They are monochrome font glyphs,
# not emoji. Edge heads and inner separators intentionally have separate
# catalogs because Powerlevel10k gives them different semantics.
CHAT_CONNECTOR_GLYPHS = {
    "left": {
        "flat": "",
        "blurred": "░▒▓",
        "angled": "\ue0b2",
        "slanted": "\ue0ba",
        "round": "\ue0b6",
    },
    "inner": {
        "angled": "\ue0b0",
        "vertical": "",
        "slanted": "\ue0bc",
        "round": "\ue0b4",
    },
    "right": {
        "flat": "",
        "blurred": "▓▒░",
        "angled": "\ue0b0",
        "slanted": "\ue0bc",
        "round": "\ue0b4",
    },
}
CHAT_FRAME_GLYPHS = {
    "square": ("┌", "┐", "└", "┘"),
    "round": ("╭", "╮", "╰", "╯"),
}
CHAT_STYLE_GLYPHS = frozenset(
    character
    for position in CHAT_CONNECTOR_GLYPHS.values()
    for glyph in position.values()
    for character in glyph
) | frozenset(
    glyph
    for frame in CHAT_FRAME_GLYPHS.values()
    for glyph in frame
)

NERD_GLYPHS = frozenset({
    NF_COIN, NF_LEVEL, NF_STAR, NF_USER, NF_USERS, NF_ONLINE, NF_OFFLINE,
    NF_SWORD, NF_BELL, NF_HEART, NF_COMMENT, NF_COMPANION, NF_CALENDAR,
    NF_BAG, NF_SEARCH, NF_GEAR,
    NF_HOME, NF_CMD, NF_TROPHY, NF_CHECK, NF_CROSS, NF_ARROW_R, NF_ARROW_L,
    NF_ARROW_U, NF_ARROW_D, NF_KEY, NF_CARDS, NF_PLANE, NF_WARNING, NF_SUN,
    NF_MOON, NF_BAN, NF_EXCHANGE, NF_REPEAT, NF_CARET_U, NF_CARET_D,
    NF_DIAMOND, NF_BULLSEYE, NF_FLAG, NF_CIRCLE_NOTCH,
    NF_HIT_HIGH, NF_HIT_FLAT, NF_HIT_LOW,
})

# 游戏布局可使用的单色符号。彩色 emoji、VS16、ZWJ 序列不在契约内。
GAME_TEXT_GLYPHS = frozenset({
    '>', '─', '│', '╭', '╮', '╰', '╯', '╴', '╶', '█', '░', '·', '┄', '┆',
})
GAME_GLYPHS = NERD_GLYPHS | GAME_TEXT_GLYPHS | CHAT_STYLE_GLYPHS

# ── 字形宽度契约 ──
# 排版量宽一律用 `window_engine.text.cell_width`（＝rich 的 `cell_len`）：中日韩文字
# 两列，其余（含全部 Nerd 图标、`─ │ ╭ · █` 等文本符号、Powerline 连接符）一列。
# 依据：字体契约是 Nerd Fonts v3 的 **Mono** 变体（README/CONTRIBUTING）；2026-10-15
# 用 fontTools 量了玩家机器上实际安装的 Sarasa Term SC Nerd Font：`a`=500、`中`=1000、
# Font Awesome 与 Octicons 图标全部 500（一列）。**不要给图标让两列**——每让一格，
# 带图标的那一行就和别的行错开一格。
# ── 面板行数限制 ──
MAX_LINES_CMD = 1000
MAX_LINES_CHAT = 500

# 右栏状态面板最多几个标签页（渲染器声明 pages 时的硬上限，见扩展契约）
GAME_STATUS_MAX_PAGES = 4

# ── 图标对齐缩进（icon_align 面板中无图标行的前缀） ──
ICON_INDENT = '  '  # 2 空格 = 光标符号(1) + 空格(1)，光标符号必须为 ASCII

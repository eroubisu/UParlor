"""
服务器配置
"""

from __future__ import annotations

import os

# 版本号（从 version.txt 读取，由 build_server.py 打包时生成）
def _get_server_version():
    """从 version.txt 读取版本号"""
    try:
        version_file = os.path.join(os.path.dirname(__file__), 'version.txt')
        if os.path.exists(version_file):
            with open(version_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception:
        pass
    return "dev"

SERVER_VERSION = _get_server_version()

# 客户端最新版本号（upload.py 上传时自动更新）
CLIENT_VERSION = "0.3.3"

# 网络配置
HOST = '0.0.0.0'
PORT = 5555

# 路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
USERS_DIR = os.path.join(DATA_DIR, 'users')
CHAT_LOG_DIR = os.path.join(DATA_DIR, 'chat_logs')
CHAT_HISTORY_DIR = os.path.join(CHAT_LOG_DIR, 'history')
DM_LOG_DIR = os.path.join(DATA_DIR, 'dm_logs')
DM_HISTORY_DIR = os.path.join(DM_LOG_DIR, 'history')

# 系统维护时间（北京时间凌晨4点）
MAINTENANCE_HOUR = 4

# 位置层级定义（基础层级 + 游戏自动注入）
# 格式: {位置: (显示名称, 父位置)}
LOCATION_HIERARCHY = {
    'lobby': ('大厅', None),
}


def register_game_locations(game_info: dict) -> None:
    """从 GAME_INFO 的 locations 字段注入位置到全局层级"""
    locations = game_info.get('locations', {})
    for loc_id, (display_name, parent) in locations.items():
        LOCATION_HIERARCHY[loc_id] = (display_name, parent)


# ── 指令表（从 commands.json 加载）──
# 格式: {位置: [{"name": str, "label": str, "desc": str}, ...]}
# "*" 为全局指令（任何位置有效），其余 key 为位置专属指令

import json

def _load_command_table() -> dict[str, list[dict]]:
    path = os.path.join(os.path.dirname(__file__), 'data', 'commands.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

COMMAND_TABLE: dict[str, list[dict]] = _load_command_table()


# 确保目录存在
os.makedirs(USERS_DIR, exist_ok=True)
os.makedirs(CHAT_LOG_DIR, exist_ok=True)
os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)

# ── 全局常量 ──

# 网络
MAX_BUFFER_SIZE = 65536         # 单客户端接收缓冲区上限（字节）
MAX_VIEWPORT_WIDTH = 500        # 客户端视口宽度上限
MAX_VIEWPORT_HEIGHT = 200       # 客户端视口高度上限

# 认证
MAX_LOGIN_ATTEMPTS = 5          # 连续密码错误上限
LOGIN_COOLDOWN = 60             # 触发限流后的冷却时间（秒）

# 时间
INVITE_EXPIRE = 240     # 邀请过期时间（秒）
BOT_DELAY = 1.5         # Bot 动作延迟（秒）

# 段位系统
BOT_TIER_THRESHOLD = 3          # Bot 对局不涨分的段位阶梯（expert+）
BOT_REWARD_DIVISOR = 2          # Bot 对局正收益除数
DEMOTION_RECOVERY_DIVISOR = 2   # 降段后恢复点数除数

# 默认头衔
DEFAULT_TITLE_ID = 'newcomer'

# 位置
DEFAULT_LOCATION = 'lobby'              # 玩家默认/回退位置

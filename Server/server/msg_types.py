"""消息类型常量 — 服务端发送消息的唯一类型定义"""

# ── 登录 ──
LOGIN_PROMPT = 'login_prompt'
LOGIN_SUCCESS = 'login_success'

# ── 聊天 ──
CHAT = 'chat'
CHAT_HISTORY = 'chat_history'
SYSTEM = 'system'

# ── 游戏 ──
GAME = 'game'
GAME_EVENT = 'game_event'
GAME_INVITE = 'game_invite'

# ── 房间 ──
ROOM_UPDATE = 'room_update'
ROOM_LEAVE = 'room_leave'

# ── 状态/位置 ──
STATUS = 'status'
ONLINE_USERS = 'online_users'
LOCATION_UPDATE = 'location_update'
COMMANDS_UPDATE = 'commands_update'

# ── 客户端动作 ──
ACTION = 'action'

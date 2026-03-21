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
GAME_INVITE_RESULT = 'game_invite_result'

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

# ── AI 同步 ──
AI_SYNC = 'ai_sync'

# ── 好友 ──
FRIEND_LIST = 'friend_list'
ALL_USERS = 'all_users'

# ── 私聊 ──
PRIVATE_CHAT = 'private_chat'
DM_HISTORY = 'dm_history'

# ── 通知 ──
FRIEND_REQUEST = 'friend_request'

# ── 名片 ──
PROFILE_CARD = 'profile_card'

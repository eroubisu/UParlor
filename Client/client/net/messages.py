"""服务器消息解析 — 将 JSON 消息转为类型化数据类"""

from __future__ import annotations
from dataclasses import dataclass, field


# ── 消息数据类 ──

@dataclass
class LoginPrompt:
    text: str

@dataclass
class LoginSuccess:
    text: str

@dataclass
class SystemMessage:
    text: str

@dataclass
class GameMessage:
    text: str
    update_last: bool = False

@dataclass
class ChatMessage:
    name: str
    text: str
    channel: int = 1
    time: str = ""

@dataclass
class ChatHistory:
    channel: int
    messages: list = field(default_factory=list)

@dataclass
class StatusUpdate:
    data: dict = field(default_factory=dict)
    location_path: str | None = None

@dataclass
class OnlineUsers:
    users: list = field(default_factory=list)

@dataclass
class GameInvite:
    raw: dict = field(default_factory=dict)

@dataclass
class RoomUpdate:
    room_data: dict | None = None
    message: str | None = None

@dataclass
class RoomLeave:
    location: str | None = None
    location_path: str | None = None
    commands: list = field(default_factory=list)

@dataclass
class GameQuit:
    location: str | None = None

@dataclass
class LocationUpdate:
    location: str
    location_path: str | None = None
    commands: list = field(default_factory=list)

@dataclass
class CommandsUpdate:
    commands: list = field(default_factory=list)

@dataclass
class GameEvent:
    game_type: str = ""
    event: str = ""
    data: dict = field(default_factory=dict)

@dataclass
class AISyncDown:
    companions: dict = field(default_factory=dict)

@dataclass
class ActionCommand:
    action: str = ""
    raw: dict = field(default_factory=dict)

@dataclass
class FriendList:
    friends: list = field(default_factory=list)

@dataclass
class AllUsers:
    users: list = field(default_factory=list)

@dataclass
class PrivateChat:
    from_name: str = ""
    from_display: str = ""
    to_name: str = ""
    text: str = ""
    time: str = ""

@dataclass
class FriendRequest:
    from_name: str = ""
    pending: list = field(default_factory=list)

@dataclass
class DMHistory:
    conversations: dict = field(default_factory=dict)


# ── 分发表 ──

_PARSERS = {
    'login_prompt':   lambda m: LoginPrompt(text=m.get('text', '')),
    'login_success':  lambda m: LoginSuccess(text=m.get('text', '')),
    'system':         lambda m: SystemMessage(text=m.get('text', '')),
    'game':           lambda m: GameMessage(text=m.get('text', ''), update_last=m.get('update_last', False)),
    'chat':           lambda m: ChatMessage(name=m.get('name', '???'), text=m.get('text', ''),
                                            channel=m.get('channel', 1), time=m.get('time', '')),
    'chat_history':   lambda m: ChatHistory(channel=m.get('channel', 1), messages=m.get('messages', [])),
    'status':         lambda m: StatusUpdate(data=m.get('data', {}), location_path=m.get('location_path')),
    'online_users':   lambda m: OnlineUsers(users=m.get('users', [])),
    'game_invite':    lambda m: GameInvite(raw=m),
    'room_update':    lambda m: RoomUpdate(room_data=m.get('room_data'), message=m.get('message')),
    'room_leave':     lambda m: RoomLeave(location=m.get('location'), location_path=m.get('location_path'),
                                            commands=m.get('commands', [])),
    'game_quit':      lambda m: GameQuit(location=m.get('location')),
    'location_update': lambda m: LocationUpdate(location=m.get('location', 'lobby'),
                                                location_path=m.get('location_path'),
                                                commands=m.get('commands', [])),
    'commands_update': lambda m: CommandsUpdate(commands=m.get('commands', [])),
    'game_event':     lambda m: GameEvent(game_type=m.get('game_type', ''), event=m.get('event', ''),
                                          data=m.get('data', {})),
    'ai_sync':        lambda m: AISyncDown(companions=m.get('companions', {})),
    'action':         lambda m: ActionCommand(action=m.get('action', ''), raw=m),
    'friend_list':    lambda m: FriendList(friends=m.get('friends', [])),
    'all_users':      lambda m: AllUsers(users=m.get('users', [])),
    'private_chat':   lambda m: PrivateChat(from_name=m.get('from', ''), from_display=m.get('from_display', ''),
                                            to_name=m.get('to', ''), text=m.get('text', ''),
                                            time=m.get('time', '')),
    'friend_request': lambda m: FriendRequest(from_name=m.get('from', ''), pending=m.get('pending', [])),
    'dm_history':     lambda m: DMHistory(conversations=m.get('conversations', {})),
}


def parse_server_message(msg: dict):
    """将原始 JSON dict 解析为对应的数据类实例。"""
    parser = _PARSERS.get(msg.get('type', 'chat'))
    if parser:
        return parser(msg)
    return GameMessage(text=msg.get('text', str(msg)))

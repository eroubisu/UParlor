"""聊天消息分发"""

from __future__ import annotations

from ..messages import (
    ChatMessage, ChatHistory, PrivateChat, DMHistory, RoomChat,
)


def _on_chat_message(parsed, app, screen, st):
    st.chat.add_world_message(parsed.name, parsed.text, parsed.time)


def _on_room_chat(parsed, app, screen, st):
    st.chat.add_room_message(parsed.name, parsed.text, parsed.time)


def _on_chat_history(parsed, app, screen, st):
    st.chat.set_world_history(parsed.messages)


def _on_private_chat(parsed, app, screen, st):
    st.chat.add_private_message(
        parsed.from_name, parsed.to_name, parsed.text, parsed.time)
    screen.update_badges()


def _on_dm_history(parsed, app, screen, st):
    st.chat.set_dm_history(parsed.conversations)
    screen.update_badges()


HANDLERS = {
    ChatMessage: _on_chat_message,
    ChatHistory: _on_chat_history,
    PrivateChat: _on_private_chat,
    DMHistory: _on_dm_history,
    RoomChat: _on_room_chat,
}

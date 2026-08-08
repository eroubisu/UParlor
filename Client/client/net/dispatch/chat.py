"""聊天消息分发"""

from __future__ import annotations

from ..messages import (
    ChatMessage, ChatHistory, PrivateChat, DMHistory, RoomChat,
)


def _on_chat_message(parsed, app, screen, st):
    st.chat.add_world_message(
        parsed.name, parsed.text, parsed.time, parsed.sender,
        parsed.message_id)


def _on_room_chat(parsed, app, screen, st):
    st.chat.add_room_message(
        parsed.name, parsed.text, parsed.time, parsed.sender)


def _on_chat_history(parsed, app, screen, st):
    if parsed.prepend:
        st.chat.prepend_world_history(parsed.messages, parsed.has_more)
    else:
        st.chat.set_world_history(parsed.messages, parsed.has_more)


def _on_private_chat(parsed, app, screen, st):
    st.chat.add_private_message(
        parsed.from_name, parsed.to_name, parsed.text, parsed.time,
        getattr(parsed, "sender", {}))
    if parsed.from_name != st.chat.player_name:
        from ...companion import CompanionController
        CompanionController.instance(st).observe_event(
            f"收到来自 {parsed.from_name} 的私聊")
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

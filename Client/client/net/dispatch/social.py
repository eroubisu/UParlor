"""社交消息分发 — 在线用户、好友、名片"""

from __future__ import annotations

from ..messages import (
    OnlineUsers, FriendList, AllUsers,
    FriendRequest, ProfileCard,
)


def _on_online_users(parsed, app, screen, st):
    st.online.update_users(parsed.users)


def _on_friend_list(parsed, app, screen, st):
    old_friends = st.online.friends
    is_init = old_friends is None
    st.online.update_friends(parsed.friends)
    if not is_init:
        old_set = set(old_friends)
        new_set = set(parsed.friends)
        for name in new_set - old_set:
            st.cmd.add_line(f"{name} 已成为你的好友")
        for name in old_set - new_set:
            st.cmd.add_line(f"{name} 已不再是你的好友")
    screen.update_badges()


def _on_all_users(parsed, app, screen, st):
    st.online.update_all_users(parsed.users)


def _on_friend_request(parsed, app, screen, st):
    if parsed.from_name:
        st.cmd.add_line(f"{parsed.from_name} 请求添加你为好友")
    if parsed.pending is not None:
        st.notify.set_friend_requests(parsed.pending)
    elif parsed.from_name:
        st.notify.add_friend_request(parsed.from_name)
    screen.update_badges()


def _on_profile_card(parsed, app, screen, st):
    st.online.set_viewed_card(parsed.data)


HANDLERS = {
    OnlineUsers: _on_online_users,
    FriendList: _on_friend_list,
    AllUsers: _on_all_users,
    FriendRequest: _on_friend_request,
    ProfileCard: _on_profile_card,
}

"""在线用户状态"""

from __future__ import annotations

from .base import BaseState


class OnlineState(BaseState):
    """在线用户面板的全部状态"""

    def __init__(self):
        super().__init__()
        self.users: list = []
        self.friends: list[str] | None = None
        self.all_users: list[str] = []
        self.tab: str = "friends"
        self.cursor: int = 0
        self.viewed_card: dict | None = None

    def update_users(self, users: list):
        self.users = users
        self._notify('update_users', users)

    def update_friends(self, friends: list[str]):
        self.friends = friends
        self._notify('update_friends', friends)

    def update_all_users(self, users: list[str]):
        self.all_users = users
        self._notify('update_all_users', users)

    def set_viewed_card(self, card_data: dict):
        self.viewed_card = card_data
        self._notify('viewed_card', card_data)

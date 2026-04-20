"""游戏面板状态"""

from __future__ import annotations

from .base import BaseState


class GameBoardState(BaseState):
    """游戏面板的全部状态"""

    def __init__(self):
        super().__init__()
        self.room_data: dict = {}
        self.games: list[dict] = []  # 可用游戏列表 [{id, name, icon, ...}]
        self.rooms: list[dict] = []  # 活跃房间列表

    def set_games(self, games: list[dict]):
        self.games = games
        self._notify('set_games', games)

    def set_rooms(self, rooms: list[dict]):
        self.rooms = rooms
        self._notify('set_rooms', rooms)

    def update_room(self, room_data: dict):
        self.room_data = room_data
        self._notify('update_room', room_data)

    def clear(self):
        self.room_data = {}
        self._notify('clear')

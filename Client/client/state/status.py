"""状态面板状态 — 名片 + 位置"""

from __future__ import annotations

from .base import BaseState


class StatusState(BaseState):
    """状态面板的全部状态（名片 + 状态 + 设置）"""

    def __init__(self):
        super().__init__()
        self.player_data: dict = {}
        self.location: str = ''
        self.location_path: str = ''

    def update_player_info(self, player_data: dict):
        self.player_data = player_data
        self._notify('update_player_info', player_data)

    def update_location(self, location: str):
        self.location = location
        self._notify('update_location', location)

    def update_location_path(self, path: str):
        self.location_path = path
        self._notify('update_location_path', path)

    def clear(self):
        self.player_data = {}
        self._notify('clear')

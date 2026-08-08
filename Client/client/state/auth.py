"""登录前认证选择状态。"""

from __future__ import annotations

from copy import deepcopy

from .base import BaseState


class AuthState(BaseState):
    def __init__(self):
        super().__init__()
        self.text = ''
        self.choices: list[dict] = []
        self.cursor = 0

    @property
    def active(self) -> bool:
        return bool(self.choices)

    def show_conflict(self, text: str, choices: list[dict]) -> None:
        self.text = text
        self.choices = deepcopy(choices)
        self.cursor = 0
        self._notify('conflict')

    def move(self, direction: int) -> None:
        if not self.choices:
            return
        self.cursor = min(
            max(self.cursor + direction, 0), len(self.choices) - 1)
        self._notify('cursor')

    def selected_id(self) -> str:
        if not self.choices:
            return ''
        return str(self.choices[self.cursor].get('id', ''))

    def clear(self) -> None:
        if not self.choices and not self.text:
            return
        self.text = ''
        self.choices = []
        self.cursor = 0
        self._notify('clear')

"""按 ModuleStateManager 隔离的游戏交互状态。"""

from __future__ import annotations

from copy import deepcopy

from .base import BaseState


class GameInteractionState(BaseState):
    """存储游戏处理器产生、棋盘渲染器观察的交互数据。"""

    def __init__(self):
        super().__init__()
        self._active_game = ''
        self._states: dict[str, dict] = {}
        self._generations: dict[str, int] = {}

    def activate(self, game_type: str) -> None:
        """切换当前游戏，并使上一游戏的延迟回调失效。"""
        if game_type == self._active_game:
            return
        changed = bool(self._states)
        for key in set(self._states) | set(self._generations):
            self._generations[key] = self._generations.get(key, 0) + 1
        self._states.clear()
        self._active_game = game_type
        if changed:
            self._notify('reset')

    def snapshot(self, game_type: str) -> dict | None:
        data = self._states.get(game_type)
        return deepcopy(data) if data is not None else None

    def replace(self, game_type: str, data: dict) -> None:
        self._active_game = game_type
        self._states[game_type] = deepcopy(data)
        self._notify('update', game_type)

    def update(self, game_type: str, **fields) -> None:
        data = self.snapshot(game_type) or {}
        data.update(fields)
        self.replace(game_type, data)

    def reset(
        self, game_type: str | None = None, *, notify: bool = True,
    ) -> None:
        keys = [game_type] if game_type else list(
            set(self._states) | set(self._generations))
        changed = False
        for key in keys:
            self._generations[key] = self._generations.get(key, 0) + 1
            changed = self._states.pop(key, None) is not None or changed
        if game_type is None:
            self._active_game = ''
        elif self._active_game == game_type:
            self._active_game = ''
        if changed and notify:
            self._notify('reset', game_type)

    def generation(self, game_type: str) -> int:
        return self._generations.get(game_type, 0)

    def is_current(self, game_type: str, generation: int) -> bool:
        return (
            self._active_game == game_type
            and self.generation(game_type) == generation
            and game_type in self._states
        )
"""State 基类 — 统一的多监听器通知机制"""

from __future__ import annotations


class BaseState:
    """State 基类 — 统一的多监听器通知机制"""

    def __init__(self):
        self._listeners: list = []

    def add_listener(self, cb):
        if cb not in self._listeners:
            self._listeners.append(cb)

    def remove_listener(self, cb):
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

    def _notify(self, event: str, *args):
        for cb in self._listeners:
            cb(event, *args)

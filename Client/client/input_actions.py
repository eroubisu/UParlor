"""Canonical physical-key mappings for the five global input actions."""

from __future__ import annotations


_DIRECTION_KEYS = {
    "up": "up", "w": "up", "k": "up",
    "down": "down", "s": "down", "j": "down",
    "left": "left", "a": "left", "h": "left",
    "right": "right", "d": "right", "l": "right",
}
_SELECT_KEYS = frozenset({"enter", "z"})
_EXIT_KEYS = frozenset({
    "escape", "x", "q", "ctrl+left_square_bracket",
})
_FOCUS_KEYS = {
    "shift+up": "k", "W": "k", "K": "k",
    "shift+down": "j", "S": "j", "J": "j",
    "shift+left": "h", "A": "h", "H": "h",
    "shift+right": "l", "D": "l", "L": "l",
}


def navigation_action(key: str) -> str | None:
    """Map direction and selection keys to the window navigation protocol."""
    direction = _DIRECTION_KEYS.get(key)
    if direction == "left":
        return "tab_prev"
    if direction == "right":
        return "tab_next"
    if direction is not None:
        return direction
    if key in _SELECT_KEYS:
        return "enter"
    return None


def focus_direction(key: str) -> str | None:
    """Map shifted direction keys to spatial panel movement."""
    return _FOCUS_KEYS.get(key)


def is_exit_key(key: str) -> bool:
    return key in _EXIT_KEYS


def is_popup_key(key: str) -> bool:
    return key == "space"


def text_input_mode(key: str) -> bool | None:
    """Return sticky state for text-input keys, or None for another action."""
    if key == "i":
        return False
    if key == "I":
        return True
    return None

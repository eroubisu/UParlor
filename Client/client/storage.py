"""本地持久化存储 — ~/.uparlor/config.json"""

from __future__ import annotations

import json
from pathlib import Path

_DIR = Path.home() / '.uparlor'
_FILE = _DIR / 'config.json'


def _load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save(data: dict) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def get_tutorial_done() -> bool:
    import os
    if os.environ.get('UPARLOR_TUTORIAL_RESET') == '1':
        return False
    return _load().get('tutorial_done', False)


def set_tutorial_done() -> None:
    data = _load()
    data['tutorial_done'] = True
    _save(data)


def get_block_ctrl_c() -> bool:
    """Return whether the application-level Ctrl+C exit is disabled."""
    return bool(_load().get("block_ctrl_c", True))


def set_block_ctrl_c(blocked: bool) -> None:
    data = _load()
    data["block_ctrl_c"] = blocked
    _save(data)


def get_world_chat_clear_marker(player_name: str) -> str:
    markers = _load().get("world_chat_clear_markers", {})
    if not isinstance(markers, dict):
        return ""
    marker = markers.get(player_name.casefold(), "")
    return marker if isinstance(marker, str) else ""


def set_world_chat_clear_marker(player_name: str, message_id: str) -> None:
    if not player_name or not message_id:
        return
    data = _load()
    markers = data.get("world_chat_clear_markers", {})
    if not isinstance(markers, dict):
        markers = {}
    markers[player_name.casefold()] = message_id
    data["world_chat_clear_markers"] = markers
    _save(data)

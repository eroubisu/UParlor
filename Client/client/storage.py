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


def get_saved_username() -> str:
    return _load().get('username', '')


def save_username(name: str) -> None:
    data = _load()
    data['username'] = name
    _save(data)


def get_tutorial_done() -> bool:
    import os
    if os.environ.get('UPARLOR_TUTORIAL_RESET') == '1':
        return False
    return _load().get('tutorial_done', False)


def set_tutorial_done() -> None:
    data = _load()
    data['tutorial_done'] = True
    _save(data)

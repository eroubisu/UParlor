"""AI 配置管理 — ~/.uparlor/ai/ 全局配置 + 角色级配置"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

AI_DIR = Path.home() / ".uparlor" / "ai"
CHARACTERS_DIR = AI_DIR / "characters"

# ── 全局配置 ──

_DEFAULT_GLOBAL = {
    "auto_start": False,
    "last_character_id": "",
    "api_key": "",
    "model": "gemini-2.5-flash",
    "attention_level": "normal",
}


def ensure_ai_dir():
    AI_DIR.mkdir(parents=True, exist_ok=True)


def _global_config_path() -> Path:
    return AI_DIR / "config.json"


def load_global_config() -> dict:
    path = _global_config_path()
    if not path.exists():
        return dict(_DEFAULT_GLOBAL)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(_DEFAULT_GLOBAL)
        merged.update(data)
        return merged
    except Exception:
        return dict(_DEFAULT_GLOBAL)


def save_global_config(data: dict):
    ensure_ai_dir()
    with open(_global_config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 角色目录管理 ──

def char_dir(char_id: str) -> Path:
    return CHARACTERS_DIR / char_id


def ensure_char_dir(char_id: str):
    char_dir(char_id).mkdir(parents=True, exist_ok=True)


def list_character_ids() -> list[str]:
    """返回所有角色 ID（即 characters/ 下的子目录名）"""
    if not CHARACTERS_DIR.exists():
        return []
    return sorted(
        d.name for d in CHARACTERS_DIR.iterdir()
        if d.is_dir() and (d / "profile.json").exists()
    )


def delete_character(char_id: str):
    d = char_dir(char_id)
    if d.exists():
        shutil.rmtree(d)


# ── 角色级 API 配置 ──

_DEFAULT_API_CONFIG = {
    "api_key": "",
    "model": "gemini-2.5-flash",
    "summary_model": "gemini-2.5-flash",
    "daily_token_limit": 100000,
    "proactive_enabled": True,
    "proactive_idle_minutes": 10,
    "proactive_cooldown_minutes": 5,
}


def load_api_config(char_id: str) -> dict:
    path = char_dir(char_id) / "api.json"
    if not path.exists():
        return dict(_DEFAULT_API_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(_DEFAULT_API_CONFIG)
        merged.update(data)
        return merged
    except Exception:
        return dict(_DEFAULT_API_CONFIG)


def save_api_config(char_id: str, data: dict):
    ensure_char_dir(char_id)
    path = char_dir(char_id) / "api.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 角色级 token 统计 ──

def load_stats(char_id: str) -> dict:
    path = char_dir(char_id) / "stats.json"
    if not path.exists():
        return {"today": "", "tokens": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"today": "", "tokens": 0}


def save_stats(char_id: str, data: dict):
    ensure_char_dir(char_id)
    path = char_dir(char_id) / "stats.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ── 通用 JSON/Text IO ──

def load_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

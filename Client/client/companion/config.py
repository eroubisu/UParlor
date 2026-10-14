"""Companion 配置管理 — 全局配置 + 按玩家隔离的角色/历史。

存储布局:
    ~/.uparlor/companion/
        config.json                  全局配置 (provider/api_key/model — 跨玩家共享)
        players/
            <player_name>/
                config.json          玩家级偏好 (enabled/last_character/attention/activity)
                stats.json           token 使用统计
                characters/
                    <char_id>/
                        profile.json
                        status.json
                        impression.json
                        recent.json
                        summary.txt
                        memory.json
"当前玩家" 由 set_current_player(name) 注入，所有 char_dir / stats / chars
都解析到该玩家子目录下。未设置时所有 list_/load_ 返回空。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from .provider import DEEPSEEK_BASE_URL

_log = logging.getLogger(__name__)

COMPANION_DIR = Path.home() / ".uparlor" / "companion"
PLAYERS_DIR = COMPANION_DIR / "players"

# ── 当前玩家 (运行期注入) ──

_current_player: str = ""


def set_current_player(name: str):
    global _current_player
    _current_player = (name or "").strip()


def player_dir(name: str | None = None) -> Path:
    n = (name or _current_player).strip()
    if not n:
        # 未登录时使用 _anon 占位（调用方应避免读写）
        return PLAYERS_DIR / "_anon"
    return PLAYERS_DIR / n


# ── 全局配置 (跨玩家共享) ──

_PROVIDER_DEFAULTS = {
    "gemini": {"api_key": "", "model": "gemini-2.5-flash"},
    "deepseek": {"api_key": "", "model": ""},
}

_DEFAULT_GLOBAL = {
    "provider": "gemini",
    "api_key": "",
    "base_url": "",
    "model": "gemini-2.5-flash",
    "providers": _PROVIDER_DEFAULTS,
}


def _default_global_config() -> dict:
    config = dict(_DEFAULT_GLOBAL)
    config["providers"] = _normalize_provider_configs(None)
    return config


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp:
            temp.write(text)
            temp.flush()
            os.fsync(temp.fileno())
            temp_path = Path(temp.name)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def load_global_config() -> dict:
    path = COMPANION_DIR / "config.json"
    if not path.exists():
        return _default_global_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = _default_global_config()
        merged.update(data)
        provider = merged.get("provider")
        if provider == "google":
            provider = "gemini"
        elif (
            provider == "openai"
            and str(merged.get("base_url", "")).rstrip("/")
            == DEEPSEEK_BASE_URL.rstrip("/")
        ):
            provider = "deepseek"
        if provider not in ("gemini", "deepseek"):
            merged.update({"api_key": "", "model": ""})
            provider = "gemini"
            data = {
                "api_key": "",
                "model": "",
                "providers": {
                    "gemini": {"api_key": "", "model": ""},
                },
            }
        providers = _normalize_provider_configs(data.get("providers"))
        if data:
            providers[provider] = {
                "api_key": str(data.get("api_key", "")),
                "model": str(data.get("model", "")),
            }
        merged["provider"] = provider
        merged["providers"] = providers
        merged.update(providers[provider])
        merged["base_url"] = (
            DEEPSEEK_BASE_URL if provider == "deepseek" else "")
        return merged
    except (OSError, json.JSONDecodeError, TypeError):
        _log.warning("Failed to load companion global config", exc_info=True)
        return _default_global_config()


def save_global_config(data: dict):
    provider = data.get("provider")
    if provider not in ("gemini", "deepseek"):
        raise ValueError(f"Unsupported companion provider: {provider!r}")
    data = dict(data)
    providers = _normalize_provider_configs(data.get("providers"))
    providers[provider] = {
        "api_key": str(data.get("api_key", "")),
        "model": str(data.get("model", "")),
    }
    data["providers"] = providers
    data["base_url"] = (
        DEEPSEEK_BASE_URL if provider == "deepseek" else "")
    _atomic_write(
        COMPANION_DIR / "config.json",
        json.dumps(data, ensure_ascii=False, indent=2),
    )


def _normalize_provider_configs(value) -> dict[str, dict[str, str]]:
    source = value if isinstance(value, dict) else {}
    normalized = {}
    for provider, defaults in _PROVIDER_DEFAULTS.items():
        item = source.get(provider)
        if not isinstance(item, dict):
            item = {}
        normalized[provider] = {
            "api_key": str(item.get("api_key", defaults["api_key"])),
            "model": str(item.get("model", defaults["model"])),
        }
    return normalized


def provider_config(config: dict, provider: str) -> dict[str, str]:
    if provider not in _PROVIDER_DEFAULTS:
        raise ValueError(f"Unsupported companion provider: {provider!r}")
    providers = _normalize_provider_configs(config.get("providers"))
    if config.get("provider") == provider:
        providers[provider] = {
            "api_key": str(config.get("api_key", "")),
            "model": str(config.get("model", "")),
        }
    return providers[provider]


# ── 玩家级偏好 ──

_DEFAULT_PLAYER = {
    "enabled": False,                  # 旅伴是否启用 (启用时后台 tick 也运行)
    "last_character_id": "",
    "attention_level": "normal",       # quiet / normal / talkative
    "activity_level": "normal",        # 主动行为强度
    "background_proactive": True,      # 启用时后台是否主动发提示
}


def load_player_config(name: str | None = None) -> dict:
    path = player_dir(name) / "config.json"
    if not path.exists():
        return dict(_DEFAULT_PLAYER)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(_DEFAULT_PLAYER)
        merged.update(data)
        return merged
    except (OSError, json.JSONDecodeError, TypeError):
        _log.warning("Failed to load companion player config", exc_info=True)
        return dict(_DEFAULT_PLAYER)


def save_player_config(data: dict, name: str | None = None):
    _atomic_write(
        player_dir(name) / "config.json",
        json.dumps(data, ensure_ascii=False, indent=2),
    )


# ── 角色目录管理 ──

def characters_dir() -> Path:
    return player_dir() / "characters"


def char_dir(char_id: str) -> Path:
    return characters_dir() / char_id


def ensure_char_dir(char_id: str):
    char_dir(char_id).mkdir(parents=True, exist_ok=True)


def list_character_ids() -> list[str]:
    base = characters_dir()
    if not base.exists():
        return []
    return sorted(
        d.name for d in base.iterdir()
        if d.is_dir() and (d / "profile.json").exists()
    )


# ── token 统计 (按玩家隔离) ──

def load_stats() -> dict:
    d = player_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / "stats.json"
    if not path.exists():
        return {"today": "", "models": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "tokens" in data and "models" not in data:
            data = {"today": data.get("today", ""), "models": {}}
        return data
    except (OSError, json.JSONDecodeError, TypeError):
        _log.warning("Failed to load companion token stats", exc_info=True)
        return {"today": "", "models": {}}


def save_stats(data: dict):
    _atomic_write(
        player_dir() / "stats.json",
        json.dumps(data, ensure_ascii=False),
    )


# ── 通用 JSON/Text IO ──

def load_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        _log.debug("load_json(%s) failed", path, exc_info=True)
        return default if default is not None else {}


def save_json(path: Path, data):
    _atomic_write(
        path,
        json.dumps(data, ensure_ascii=False, indent=2),
    )


def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_text(path: Path, text: str):
    _atomic_write(path, text)

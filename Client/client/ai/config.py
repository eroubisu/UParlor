"""AI 配置管理 — ~/.uparlor/ai/ 全局配置 + 角色级配置"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

_log = logging.getLogger(__name__)

AI_DIR = Path.home() / ".uparlor" / "ai"
CHARACTERS_DIR = AI_DIR / "characters"

# ── 全局配置 ──

_DEFAULT_GLOBAL = {
    "auto_start": False,
    "last_character_id": "",
    "provider": "google",
    "api_key": "",
    "base_url": "",
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
    "provider": "",
    "api_key": "",
    "base_url": "",
    "model": "",
    "summary_model": "",
    "proactive_enabled": True,
    "proactive_idle_minutes": 10,
    "proactive_cooldown_minutes": 5,
}


def load_api_config(char_id: str) -> dict:
    """加载角色级 API 配置（不合并默认值，缺失字段由 _resolve_config 降级到全局）"""
    path = char_dir(char_id) / "api.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_api_config(char_id: str, data: dict):
    ensure_char_dir(char_id)
    path = char_dir(char_id) / "api.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 全局 token 统计 ──

def load_stats() -> dict:
    ensure_ai_dir()
    path = AI_DIR / "stats.json"
    if not path.exists():
        return {"today": "", "models": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 兼容旧版扁平格式
        if "tokens" in data and "models" not in data:
            data = {"today": data.get("today", ""), "models": {}}
        return data
    except Exception:
        return {"today": "", "models": {}}


def save_stats(data: dict):
    ensure_ai_dir()
    path = AI_DIR / "stats.json"
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
        _log.debug("load_json(%s) failed", path, exc_info=True)
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


# ── 多设备同步 ──

# 需要同步的文件（不含 api.json / stats.json — 设备专属）
_SYNC_FILES = ("profile.json", "status.json", "impression.json", "recent.json", "memory.json")
_SYNC_TEXT = ("summary.txt",)


def export_all_chars() -> dict:
    """导出所有角色数据，用于上传到服务器同步。

    返回 ``{char_id: {profile: {}, status: {}, ...}}``。
    不包含 api.json（含 api_key）。
    """
    result: dict = {}
    for cid in list_character_ids():
        d = char_dir(cid)
        char_data: dict = {}
        for name in _SYNC_FILES:
            char_data[name] = load_json(d / name, {})
        for name in _SYNC_TEXT:
            char_data[name] = load_text(d / name)
        result[cid] = char_data
    return result


def import_all_chars(data: dict):
    """从服务器下载的数据合并到本地。

    合并策略：以 ``profile.json`` 中的 ``updated_at`` 为准，
    时间戳更新的一方覆盖另一方。本地无此角色时直接写入。
    """
    if not isinstance(data, dict):
        return
    for cid, char_data in data.items():
        if not isinstance(char_data, dict):
            continue
        d = char_dir(cid)
        local_profile = load_json(d / "profile.json", {})
        remote_profile = char_data.get("profile.json", {})
        local_ts = local_profile.get("updated_at", "")
        remote_ts = remote_profile.get("updated_at", "")
        # 本地不存在或远端更新 → 写入
        if not local_profile or remote_ts >= local_ts:
            ensure_char_dir(cid)
            for name in _SYNC_FILES:
                if name in char_data:
                    save_json(d / name, char_data[name])
            for name in _SYNC_TEXT:
                if name in char_data:
                    save_text(d / name, char_data[name])

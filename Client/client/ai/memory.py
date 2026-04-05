"""轻量记忆检索 — 纯 JSON + 关键词匹配（按角色隔离）"""

from __future__ import annotations

import re
import time
from collections import Counter

from .config import char_dir, load_json, save_json, ensure_char_dir

_MAX_HISTORY = 500

# 内存缓存：避免每次 search 都读磁盘
_cache: dict[str, list[dict]] = {}  # char_id → history
_cache_id: str = ""  # 当前缓存的 char_id（仅缓存一个）


def _history_path(char_id: str):
    return char_dir(char_id) / "memory.json"


def _load_history(char_id: str) -> list[dict]:
    global _cache_id
    if char_id == _cache_id and char_id in _cache:
        return _cache[char_id]
    data = load_json(_history_path(char_id), [])
    _cache_id = char_id
    _cache.clear()
    _cache[char_id] = data
    return data


def _save_history(char_id: str, entries: list[dict]):
    global _cache_id
    ensure_char_dir(char_id)
    trimmed = entries[-_MAX_HISTORY:]
    save_json(_history_path(char_id), trimmed)
    _cache_id = char_id
    _cache.clear()
    _cache[char_id] = trimmed


def invalidate_cache():
    """角色切换时清除缓存"""
    global _cache_id
    _cache.clear()
    _cache_id = ""


def _tokenize(text: str) -> list[str]:
    return re.findall(r'[a-zA-Z]{2,}|[\u4e00-\u9fff]', text.lower())


def _score(query_tokens: Counter, doc_tokens: Counter) -> float:
    overlap = query_tokens & doc_tokens
    return sum(overlap.values())


def store_messages(char_id: str, messages: list[dict]):
    """将对话消息追加到角色历史库"""
    history = _load_history(char_id)
    ts = int(time.time())
    for m in messages:
        history.append({
            "role": m["role"],
            "content": m["content"],
            "ts": ts,
        })
    _save_history(char_id, history)


def search(char_id: str, query: str, n: int = 5) -> list[str]:
    """基于关键词匹配，从角色历史中检索最相关的 n 条"""
    history = _load_history(char_id)
    if not history:
        return []

    q_tokens = Counter(_tokenize(query))
    if not q_tokens:
        return []

    scored = []
    for entry in history:
        text = entry.get("content", "")
        d_tokens = Counter(_tokenize(text))
        s = _score(q_tokens, d_tokens)
        if s > 0:
            role = entry.get("role", "?")
            scored.append((s, f"{role}: {text}"))

    scored.sort(key=lambda x: -x[0])
    return [text for _, text in scored[:n]]

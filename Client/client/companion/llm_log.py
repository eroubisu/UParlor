"""LLM 调用日志 — 通过环境变量 UPARLOR_LLM_LOG=1 开启

每次 service.chat() / proactive_chat() / _compress() 触发的 LLM 请求
都会被记录到 <player_dir>/llm_debug.jsonl, 每行一个 JSON, 含:
  - ts: ISO 时间
  - kind: 'chat' / 'proactive' / 'compress' / 'tool'
  - model: 模型名
  - messages: 输入消息列表 (system + history)
  - output: 文本响应 (或工具调用名)
  - tokens: token 用量
  - error: 出错时的错误信息

用途: 后期复盘 / 调试 prompt 注入 / 评估 token 消耗

不与 service.py 紧耦合: service 代码不引用此模块, 由 provider 装饰器自动注入。
若环境变量未设置, 完全 no-op (零开销)。
"""

from __future__ import annotations

import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# 环境变量开关
ENABLED: bool = os.environ.get("UPARLOR_LLM_LOG", "0") not in ("", "0", "false", "no")


def _log_path() -> Path | None:
    """日志文件路径 (当前玩家目录下)"""
    try:
        from . import config as cfg
        d = cfg.player_dir()
        if not d:
            return None
        return d / "llm_debug.jsonl"
    except Exception:
        return None


def record(kind: str, **payload: Any) -> None:
    """追加一行日志。kind ∈ {'chat','proactive','compress','tool','error'}"""
    if not ENABLED:
        return
    path = _log_path()
    if path is None:
        return
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        **payload,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        _log.debug("llm_log.record failed", exc_info=True)


def is_enabled() -> bool:
    return ENABLED

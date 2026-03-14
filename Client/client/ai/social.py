"""L1 好感系统 — 亲密/信任/熟悉 三值 + 关系阶段"""

from __future__ import annotations

import json
from pathlib import Path

# 加载增益表和阶段配置
_CONFIG_PATH = Path(__file__).parent / "social_config.json"
try:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
        _SOCIAL_CONFIG = json.load(_f)
except (FileNotFoundError, json.JSONDecodeError):
    _SOCIAL_CONFIG = {"gain_table": {}, "stages": []}

_GAIN_TABLE: dict[str, dict[str, float]] = _SOCIAL_CONFIG.get("gain_table", {})
_STAGES: list[dict] = _SOCIAL_CONFIG.get("stages", [])


class SocialState:
    """好感三值 + 关系阶段（带迟滞防抖）"""

    def __init__(self, data: dict | None = None):
        d = data or {}
        self.intimacy: float = d.get("intimacy", 0.0)
        self.trust: float = d.get("trust", 0.0)
        self.familiarity: float = d.get("familiarity", 0.0)
        self._stage: str = d.get("stage", "stranger")

    def to_dict(self) -> dict:
        return {
            "intimacy": round(self.intimacy, 2),
            "trust": round(self.trust, 2),
            "familiarity": round(self.familiarity, 2),
            "stage": self._stage,
        }

    # ── 阶段计算（带迟滞）──

    @property
    def stage(self) -> str:
        return self._stage

    @property
    def stage_label(self) -> str:
        for s in _STAGES:
            if s["id"] == self._stage:
                return s["label"]
        return self._stage

    def recalc_stage(self):
        """根据当前三值重新计算阶段（迟滞防抖）"""
        current_idx = self._stage_index(self._stage)

        # 尝试升级
        for i in range(len(_STAGES) - 1, current_idx, -1):
            s = _STAGES[i]
            enter = s["enter"]
            if (self.familiarity >= enter.get("familiarity", 0) and
                self.trust >= enter.get("trust", -999) and
                self.intimacy >= enter.get("intimacy", -999)):
                self._stage = s["id"]
                return

        # 尝试降级（用 exit 阈值）
        if current_idx > 0:
            curr = _STAGES[current_idx]
            exit_cond = curr.get("exit")
            if exit_cond:
                if (self.familiarity < exit_cond.get("familiarity", 0) or
                    self.trust < exit_cond.get("trust", -999) or
                    self.intimacy < exit_cond.get("intimacy", -999)):
                    self._stage = _STAGES[current_idx - 1]["id"]

    def _stage_index(self, stage_id: str) -> int:
        for i, s in enumerate(_STAGES):
            if s["id"] == stage_id:
                return i
        return 0

    # ── 增益 ──

    def apply_gains(self, interaction_type: str):
        """根据互动类型应用增益"""
        gains = _GAIN_TABLE.get(interaction_type)
        if not gains:
            return
        self.intimacy = max(-100, min(100, self.intimacy + gains.get("intimacy", 0)))
        self.trust = max(-50, min(100, self.trust + gains.get("trust", 0)))
        self.familiarity = max(0, min(100, self.familiarity + gains.get("familiarity", 0)))
        self.recalc_stage()

    def apply_delta(self, intimacy: float = 0, trust: float = 0, familiarity: float = 0):
        """直接增减（Phase 2 反思结果）"""
        self.intimacy = max(-100, min(100, self.intimacy + intimacy))
        self.trust = max(-50, min(100, self.trust + trust))
        self.familiarity = max(0, min(100, self.familiarity + familiarity))
        self.recalc_stage()

    # ── Prompt 注入 ──

    def to_prompt_text(self) -> str:
        return (
            f"关系阶段: {self.stage_label}\n"
            f"亲密度: {self.intimacy:.0f}/100, "
            f"信任度: {self.trust:.0f}/100, "
            f"熟悉度: {self.familiarity:.0f}/100"
        )

    # ── 显示 ──

    def to_display(self) -> dict:
        return {
            "stage": self.stage_label,
            "intimacy": round(self.intimacy),
            "trust": round(self.trust),
            "familiarity": round(self.familiarity),
        }

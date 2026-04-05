"""L1 好感系统 — 亲密/信任/熟悉 三值 + 关系阶段"""

from __future__ import annotations

import json
from pathlib import Path

# 加载增益表和阶段配置
_CONFIG_PATH = Path(__file__).parent / "data" / "social_config.json"
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

    # ── 增益（递减收益） ──

    @staticmethod
    def _diminish(current: float, gain: float, curve: float) -> float:
        """正向增益递减；负向损失放大"""
        if gain > 0:
            ratio = max(0.0, current) / 100.0
            return gain * (1.0 - ratio) ** curve
        if gain < 0:
            # 值越高时背叛越痛
            amplifier = 1.0 + max(0.0, current) / 100.0
            return gain * amplifier
        return 0.0

    def apply_gains(self, interaction_type: str):
        """根据互动类型应用增益（带递减）"""
        gains = _GAIN_TABLE.get(interaction_type)
        if not gains:
            return
        di = self._diminish(self.intimacy, gains.get("intimacy", 0), 1.5)
        dt = self._diminish(self.trust, gains.get("trust", 0), 2.0)
        df = self._diminish(self.familiarity, gains.get("familiarity", 0), 1.0)
        self.intimacy = max(-100, min(100, self.intimacy + di))
        self.trust = max(-50, min(100, self.trust + dt))
        self.familiarity = max(0, min(100, self.familiarity + df))
        self.recalc_stage()

    def apply_delta(self, intimacy: float = 0, trust: float = 0, familiarity: float = 0):
        """直接增减（Phase 2 反思结果，同样递减）"""
        di = self._diminish(self.intimacy, intimacy, 1.5)
        dt = self._diminish(self.trust, trust, 2.0)
        df = self._diminish(self.familiarity, familiarity, 1.0)
        self.intimacy = max(-100, min(100, self.intimacy + di))
        self.trust = max(-50, min(100, self.trust + dt))
        self.familiarity = max(0, min(100, self.familiarity + df))
        self.recalc_stage()

    # ── Prompt 注入 ──

    def to_prompt_text(self) -> str:
        text = (
            f"关系阶段: {self.stage_label}\n"
            f"亲密度: {self.intimacy:.0f}/100, "
            f"信任度: {self.trust:.0f}/100, "
            f"熟悉度: {self.familiarity:.0f}/100"
        )
        text += f"\n{self._behavior_hint()}"
        return text

    def _behavior_hint(self) -> str:
        """根据关系阶段和三值返回行为指引"""
        stage = self._stage
        hints = []
        if stage == "stranger":
            hints.append("你和玩家不熟。说话保持礼貌但有距离感，不要主动亲近，遇到冒犯可以直接拒绝。")
        elif stage == "acquaintance":
            hints.append("你和玩家刚认识。可以正常聊天但不会说心里话，也不会主动撒娇或发脾气。")
        elif stage == "friend":
            hints.append("你和玩家是朋友。可以开玩笑、偶尔吐槽、分享一些日常想法。")
        elif stage == "close_friend":
            hints.append("你和玩家很亲近。可以说心里话、撒娇、闹别扭。被欺负了会真的难过而不是回避。")
        elif stage == "partner":
            hints.append("你和玩家是最亲密的搭档。情绪反应最真实最强烈，可以任性、吃醋、担心。")
        if self.trust < 10:
            hints.append("你对玩家几乎没有信任，不会把弱点暴露给对方。")
        elif self.trust < 30:
            hints.append("你对玩家的信任不高，重要的事不会轻易说。")
        if self.intimacy < 0:
            hints.append("你对玩家有些反感，态度冷淡。")
        return " ".join(hints)

    # ── 显示 ──

    def to_display(self) -> dict:
        return {
            "stage": self.stage_label,
            "intimacy": round(self.intimacy),
            "trust": round(self.trust),
            "familiarity": round(self.familiarity),
        }

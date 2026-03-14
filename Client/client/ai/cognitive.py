"""L3 认知状态 — 在想什么/想说什么/期待什么"""

from __future__ import annotations


class CognitiveState:
    """认知状态：驱动主动搭话和内心想法的注入"""

    def __init__(self, data: dict | None = None):
        d = data or {}
        self.on_mind: str = d.get("on_mind", "")
        self.wants_to_say: str = d.get("wants_to_say", "")
        self.anticipating: str = d.get("anticipating", "")
        self.day_assessment: str = d.get("day_assessment", "")

    def to_dict(self) -> dict:
        return {
            "on_mind": self.on_mind,
            "wants_to_say": self.wants_to_say,
            "anticipating": self.anticipating,
            "day_assessment": self.day_assessment,
        }

    def update(self, data: dict):
        if "on_mind" in data:
            self.on_mind = data["on_mind"]
        if "wants_to_say" in data:
            self.wants_to_say = data["wants_to_say"]
        if "anticipating" in data:
            self.anticipating = data["anticipating"]
        if "day_assessment" in data:
            self.day_assessment = data["day_assessment"]

    def to_prompt_text(self) -> str:
        parts = []
        if self.on_mind:
            parts.append(f"你现在在想: {self.on_mind}")
        if self.wants_to_say:
            parts.append(f"你其实想说: {self.wants_to_say}")
        if self.anticipating:
            parts.append(f"你在期待: {self.anticipating}")
        if self.day_assessment:
            parts.append(f"今天的感受: {self.day_assessment}")
        return "\n".join(parts)

    @property
    def has_something_to_say(self) -> bool:
        return bool(self.wants_to_say)

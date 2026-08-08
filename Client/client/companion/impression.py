"""M2 印象系统 — AI 眼中的你"""

from __future__ import annotations


class ImpressionState:
    """AI 对玩家的综合印象（定期由 LLM 合成更新）"""

    def __init__(self, data: dict | None = None):
        d = data or {}
        self.portrait: str = d.get("portrait", "")
        self.relationship_arc: str = d.get("relationship_arc", "")
        self.shared_references: list[str] = d.get("shared_references", [])
        self.patterns: list[str] = d.get("patterns", [])
        self.concerns: list[str] = d.get("concerns", [])

    def to_dict(self) -> dict:
        return {
            "portrait": self.portrait,
            "relationship_arc": self.relationship_arc,
            "shared_references": self.shared_references,
            "patterns": self.patterns,
            "concerns": self.concerns,
        }

    def update(self, data: dict):
        if "portrait" in data:
            self.portrait = data["portrait"]
        if "relationship_arc" in data:
            self.relationship_arc = data["relationship_arc"]
        if "shared_references" in data:
            self.shared_references = data["shared_references"]
        if "patterns" in data:
            self.patterns = data["patterns"]
        if "concerns" in data:
            self.concerns = data["concerns"]

    def to_prompt_text(self) -> str:
        parts = []
        if self.portrait:
            parts.append(f"你对玩家的印象: {self.portrait}")
        if self.relationship_arc:
            parts.append(f"关系变化: {self.relationship_arc}")
        if self.shared_references:
            parts.append(f"共同回忆: {', '.join(self.shared_references[:5])}")
        if self.patterns:
            parts.append(f"玩家习惯: {', '.join(self.patterns[:3])}")
        if self.concerns:
            parts.append(f"你在意的事: {', '.join(self.concerns[:3])}")
        return "\n".join(parts)

"""L2 心情系统 — 主情绪 + 强度 + 时间衰减"""

from __future__ import annotations

import time

# 9 种基础心情
MOODS = {
    "calm":    "平静",
    "joyful":  "开心",
    "excited": "兴奋",
    "shy":     "害羞",
    "annoyed": "烦躁",
    "anxious": "焦虑",
    "sad":     "难过",
    "angry":   "生气",
    "lonely":  "寂寞",
}

# 衰减配置：(小时数, 衰减比例)
_DECAY_POSITIVE = (2.0, 0.7)    # 正面情绪 2h 后衰减到 70%
_DECAY_NEGATIVE = (4.0, 0.7)    # 一般负面 4h 后衰减
_DECAY_EXTREME  = (8.0, 0.7)    # 强负面 8h 衰减
_POSITIVE = {"joyful", "excited", "shy"}
_EXTREME  = {"angry", "lonely"}

# 心情图标（纯文本字符，禁止 Emoji）
MOOD_ICONS = {
    "calm":    "○",
    "joyful":  "◆",
    "excited": "◇",
    "shy":     "△",
    "annoyed": "▽",
    "anxious": "◈",
    "sad":     "▼",
    "angry":   "■",
    "lonely":  "□",
}


class MoodState:
    """心情状态：主情绪 + 副情绪 + 强度 + 来源 + 衰减"""

    def __init__(self, data: dict | None = None):
        d = data or {}
        self.primary: str = d.get("primary", "calm")
        self.secondary: str = d.get("secondary", "")
        self.intensity: float = d.get("intensity", 0.3)
        self.source: str = d.get("source", "")
        self.updated_at: float = d.get("updated_at", time.time())

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "intensity": round(self.intensity, 2),
            "source": self.source,
            "updated_at": self.updated_at,
        }

    # ── 衰减 ──

    def decay(self):
        """根据时间自动衰减。calm 不衰减。"""
        if self.primary == "calm":
            return
        elapsed_h = (time.time() - self.updated_at) / 3600
        if self.primary in _POSITIVE:
            threshold, ratio = _DECAY_POSITIVE
        elif self.primary in _EXTREME:
            threshold, ratio = _DECAY_EXTREME
        else:
            threshold, ratio = _DECAY_NEGATIVE

        if elapsed_h >= threshold:
            cycles = elapsed_h / threshold
            self.intensity *= ratio ** cycles
            if self.intensity < 0.1:
                self.primary = "calm"
                self.secondary = ""
                self.intensity = 0.3
                self.source = ""
            self.updated_at = time.time()

    # ── 设置新心情 ──

    def set_mood(self, primary: str, intensity: float = 0.5,
                 secondary: str = "", source: str = ""):
        if primary in MOODS:
            self.primary = primary
        self.intensity = max(0.0, min(1.0, intensity))
        self.secondary = secondary
        self.source = source
        self.updated_at = time.time()

    # ── Prompt 注入 ──

    def to_prompt_text(self) -> str:
        label = MOODS.get(self.primary, self.primary)
        text = f"当前心情: {label} (强度 {self.intensity:.0%})"
        if self.secondary:
            sec_label = MOODS.get(self.secondary, self.secondary)
            text += f"，内心其实有些{sec_label}"
        if self.source:
            text += f"，原因: {self.source}"
        return text

    # ── 显示 ──

    def to_display(self) -> tuple[str, str, float]:
        """返回 (心情名, 图标, 强度)"""
        label = MOODS.get(self.primary, self.primary)
        icon = MOOD_ICONS.get(self.primary, "○")
        return label, icon, self.intensity

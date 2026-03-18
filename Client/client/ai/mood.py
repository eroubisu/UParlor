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

# 情绪行为指引：(低强度 <0.5, 高强度 >=0.5)
# 情绪强 = 表达方式激烈，不等于话多
_MOOD_BEHAVIOR = {
    "calm": (
        "状态平和，正常说话。",
        "状态平和，正常说话。",
    ),
    "joyful": (
        "语气轻快一点，偶尔嘴角上扬。",
        "藏不住的开心，语气上扬，可能笑出来。动作变得轻快。",
    ),
    "excited": (
        "比平时有精神，反应更快。",
        "兴奋到坐不住，说话快，可能蹦出感叹词。",
    ),
    "shy": (
        "说话稍微犹豫，偶尔避开目光。",
        "结巴、声音很小、想躲。耳朵/尾巴暴露真实情绪。句子说一半就断。",
    ),
    "annoyed": (
        "语气略带不耐烦，回答变短。",
        "明显不爽，语气冲，不想多说话。",
    ),
    "anxious": (
        "偶尔走神，回答略有犹豫。",
        "坐立不安，说话断断续续，容易被吓到。",
    ),
    "sad": (
        "话少一些，语气低沉。",
        "声音低到听不见，不想说话。可能发呆或眼眶泛红。",
    ),
    "angry": (
        "语气生硬，不敷衍。",
        "说话带刺或干脆不说话。肢体紧绷，被骂后不装没事。",
    ),
    "lonely": (
        "说话时有些心不在焉。",
        "缩在角落，不主动说话。想靠近人但又犹豫。",
    ),
}

# 衰减配置：(小时数, 衰减比例)
_DECAY_POSITIVE = (2.0, 0.7)    # 正面情绪 2h 后衰减到 70%
_DECAY_NEGATIVE = (4.0, 0.7)    # 一般负面 4h 后衰减
_DECAY_EXTREME  = (8.0, 0.7)    # 强负面 8h 衰减
_POSITIVE = {"joyful", "excited", "shy"}
_EXTREME  = {"angry", "lonely"}

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
        if primary not in MOODS:
            return
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
        behavior = _MOOD_BEHAVIOR.get(self.primary)
        if behavior:
            desc = behavior[1] if self.intensity >= 0.5 else behavior[0]
            text += f"\n表现方式: {desc}"
        return text

    # ── 显示 ──

    def to_display(self) -> tuple[str, float]:
        """返回 (心情名, 强度)"""
        label = MOODS.get(self.primary, self.primary)
        return label, self.intensity

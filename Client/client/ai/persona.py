"""AI 人设 — 从 Character 生成 system prompt 文本"""

from __future__ import annotations

from .character import Character


def character_to_system_text(char: Character) -> str:
    """将 Character 对象转为 system prompt 片段"""
    parts = []
    if char.name:
        parts.append(f"你的名字是{char.name}。")
    if char.personality:
        parts.append(f"性格: {char.personality}")
    if char.speech_style:
        parts.append(f"说话风格: {char.speech_style}")
    if char.appearance:
        parts.append(f"外貌: {char.appearance}")
    if char.backstory:
        parts.append(f"背景: {char.backstory}")
    for rule in char.custom_rules:
        parts.append(rule)
    return "\n".join(parts)

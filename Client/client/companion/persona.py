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


def format_companion_reply(arguments: dict) -> str:
    """Validate and render one provider-structured companion reply."""
    action = arguments.get("action", "")
    speech = arguments.get("speech", "")
    if not isinstance(action, str) or not isinstance(speech, str):
        raise ValueError("旅伴回复结构中的动作和台词必须是文本")
    action = action.strip()
    speech = speech.strip()
    if not action and not speech:
        raise ValueError("旅伴回复结构不能为空")
    if any(char in action for char in "*\r\n"):
        raise ValueError("旅伴动作必须是不含星号的单段文本")
    if any(char in speech for char in "*\r\n"):
        raise ValueError("旅伴台词必须是不含动作标记的单段文本")
    return "\n".join(
        part for part in (f"*{action}*" if action else "", speech) if part
    )

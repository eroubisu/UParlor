"""角色管理 — 创建、加载、保存、列表"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import (
    char_dir, ensure_char_dir, list_character_ids,
    load_json, save_json,
)


@dataclass
class Character:
    id: str
    name: str = ""
    personality: str = ""
    speech_style: str = ""
    appearance: str = ""
    backstory: str = ""
    custom_rules: list[str] = field(default_factory=list)
    created_at: float = 0.0


@dataclass
class CharacterSummary:
    id: str
    name: str


def _profile_path(char_id: str) -> Path:
    return char_dir(char_id) / "profile.json"


def load_character(char_id: str) -> Character | None:
    data = load_json(_profile_path(char_id), None)
    if data is None:
        return None
    return Character(
        id=char_id,
        name=data.get("name", ""),
        personality=data.get("personality", ""),
        speech_style=data.get("speech_style", ""),
        appearance=data.get("appearance", ""),
        backstory=data.get("backstory", ""),
        custom_rules=data.get("custom_rules", []),
        created_at=data.get("created_at", 0.0),
    )


def save_character(char: Character):
    ensure_char_dir(char.id)
    data = asdict(char)
    from datetime import datetime, timezone
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(_profile_path(char.id), data)


def list_characters() -> list[CharacterSummary]:
    result = []
    for cid in list_character_ids():
        data = load_json(_profile_path(cid), {})
        result.append(CharacterSummary(id=cid, name=data.get("name", cid)))
    return result


def generate_char_id() -> str:
    """生成唯一角色 ID"""
    return f"char_{int(time.time())}"


def _extract_json(text: str) -> dict:
    """从 LLM 文本响应中提取 JSON 对象"""
    # 去除 markdown 代码块标记
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in text")
    # 深度追踪大括号，正确处理字符串内的 {}
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == '\\':
            if in_string:
                escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError("Unmatched braces in JSON")


# ── Gemini 结构化提取 ──

_STRUCTURIZE_INSTRUCTION = """\
你是角色设定整理师。将用户的自由描述拆解到下面 6 个字段里。
规则：
- 原文里明确提到的信息必须**原样保留**，不要概括、缩写或丢弃任何细节
- 每个字段写完整的句子，不是关键词罗列
- 只有原文完全没涉及的字段才填合理默认值
- 只输出 JSON"""


def _check_truncation(resp) -> None:
    """检查 Gemini 响应是否因 token 上限被截断"""
    candidates = getattr(resp, "candidates", None)
    if candidates and candidates[0].finish_reason and \
       candidates[0].finish_reason.name == "MAX_TOKENS":
        raise ValueError("描述过长，请精简后重试")


_CHAR_SCHEMA = {
    "type": "object",
    "properties": {
        "name":         {"type": "string", "description": "角色名字"},
        "personality":  {"type": "string", "description": "性格特点：内向/外向、优缺点、矛盾面等"},
        "speech_style": {"type": "string", "description": "说话风格：语气、口头禅、情绪表达方式等"},
        "appearance":   {"type": "string", "description": "外貌：身高、发色、瞳色、体型、特征部位等"},
        "backstory":    {"type": "string", "description": "背景故事：种族、身份、日常生活、经济状况等"},
        "custom_rules": {
            "type": "array",
            "items": {"type": "string"},
            "description": "角色扮演时必须遵守的行为规则",
        },
    },
    "required": ["name", "personality", "speech_style", "appearance", "backstory", "custom_rules"],
}


async def structurize_description(desc: str, api_key: str) -> tuple[Character, int]:
    """调用 Gemini 将自由文本提取为结构化 Character。返回 (角色, token用量)。"""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=_STRUCTURIZE_INSTRUCTION,
        max_output_tokens=4000,
        temperature=0.2,
        response_mime_type="application/json",
        response_schema=_CHAR_SCHEMA,
    )
    resp = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"请从以下描述中提取完整角色设定，所有细节都要保留：\n\n{desc}",
        config=config,
    )
    _check_truncation(resp)
    data = json.loads(resp.text or "{}")
    usage = resp.usage_metadata
    tokens = usage.total_token_count if usage and usage.total_token_count else 0

    char_id = generate_char_id()
    return Character(
        id=char_id,
        name=data.get("name", "未命名"),
        personality=data.get("personality", ""),
        speech_style=data.get("speech_style", ""),
        appearance=data.get("appearance", ""),
        backstory=data.get("backstory", ""),
        custom_rules=data.get("custom_rules", []),
        created_at=time.time(),
    ), tokens


_REFINE_INSTRUCTION = "根据用户的修改意见调整角色设定，输出调整后的完整 JSON。保留未被修改的字段原值。"


async def refine_character(char: Character, feedback: str, api_key: str) -> tuple[Character, int]:
    """根据用户反馈调整角色设定。返回 (角色, token用量)。"""
    from google import genai
    from google.genai import types

    current = json.dumps({
        "name": char.name,
        "personality": char.personality,
        "speech_style": char.speech_style,
        "appearance": char.appearance,
        "backstory": char.backstory,
        "custom_rules": char.custom_rules,
    }, ensure_ascii=False, indent=2)
    prompt = f"当前角色设定:\n{current}\n\n用户的修改意见: {feedback}"

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=_REFINE_INSTRUCTION,
        max_output_tokens=4000,
        temperature=0.2,
        response_mime_type="application/json",
        response_schema=_CHAR_SCHEMA,
    )
    resp = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=config,
    )
    _check_truncation(resp)
    data = json.loads(resp.text or "{}")
    usage = resp.usage_metadata
    tokens = usage.total_token_count if usage and usage.total_token_count else 0

    char.name = data.get("name", char.name)
    char.personality = data.get("personality", char.personality)
    char.speech_style = data.get("speech_style", char.speech_style)
    char.appearance = data.get("appearance", char.appearance)
    char.backstory = data.get("backstory", char.backstory)
    char.custom_rules = data.get("custom_rules", char.custom_rules)
    return char, tokens

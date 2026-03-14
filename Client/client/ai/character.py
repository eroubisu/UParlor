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
    save_json(_profile_path(char.id), asdict(char))


def list_characters() -> list[CharacterSummary]:
    result = []
    for cid in list_character_ids():
        data = load_json(_profile_path(cid), {})
        result.append(CharacterSummary(id=cid, name=data.get("name", cid)))
    return result


def generate_char_id() -> str:
    """生成唯一角色 ID"""
    return f"char_{int(time.time())}"


# ── Gemini 结构化提取 ──

_STRUCTURIZE_PROMPT = """\
将用户的自由角色描述提取为 JSON 人设。
输出格式（只输出 JSON，不要其他文字）:
{
  "name": "角色名字",
  "personality": "性格特点",
  "speech_style": "说话风格",
  "appearance": "外貌描述",
  "backstory": "背景故事",
  "custom_rules": ["特殊规则1", "特殊规则2"]
}
如果用户没提到某字段，填写合理的默认值。name 必须有值。"""


async def structurize_description(desc: str, api_key: str) -> Character:
    """调用 Gemini 将自由文本提取为结构化 Character"""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=_STRUCTURIZE_PROMPT,
        max_output_tokens=400,
        temperature=0.3,
    )
    resp = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=desc,
        config=config,
    )
    text = (resp.text or "").strip()
    if "{" in text:
        text = text[text.index("{"):text.rindex("}") + 1]
    data = json.loads(text)

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
    )


_REFINE_PROMPT = """\
根据用户的修改意见调整角色设定。
当前设定和用户意见已提供。请输出调整后的完整 JSON（只输出 JSON，不要其他文字）:
{
  "name": "角色名字",
  "personality": "性格特点",
  "speech_style": "说话风格",
  "appearance": "外貌描述",
  "backstory": "背景故事",
  "custom_rules": ["特殊规则1", "特殊规则2"]
}"""


async def refine_character(char: Character, feedback: str, api_key: str) -> Character:
    """根据用户反馈调整角色设定"""
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
        system_instruction=_REFINE_PROMPT,
        max_output_tokens=400,
        temperature=0.3,
    )
    resp = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=config,
    )
    text = (resp.text or "").strip()
    if "{" in text:
        text = text[text.index("{"):text.rindex("}") + 1]
    data = json.loads(text)

    char.name = data.get("name", char.name)
    char.personality = data.get("personality", char.personality)
    char.speech_style = data.get("speech_style", char.speech_style)
    char.appearance = data.get("appearance", char.appearance)
    char.backstory = data.get("backstory", char.backstory)
    char.custom_rules = data.get("custom_rules", char.custom_rules)
    return char

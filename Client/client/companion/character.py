"""角色管理 — 创建、加载、保存、列表"""

from __future__ import annotations

import json
import shutil
import uuid
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
    if _profile_path(char.id).exists():
        raise FileExistsError(f"Character already exists: {char.id}")
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


def delete_character(char_id: str) -> None:
    """Delete one resolved character directory and all of its state."""
    if char_id not in list_character_ids():
        raise FileNotFoundError(f"Character does not exist: {char_id}")
    shutil.rmtree(char_dir(char_id))


def generate_char_id() -> str:
    """Generate a collision-resistant character ID."""
    while True:
        char_id = f"char_{uuid.uuid4().hex}"
        if not char_dir(char_id).exists():
            return char_id


def _extract_json(text: str) -> dict:
    """从 LLM 文本响应中提取 JSON 对象"""
    # 去除 markdown 代码块标记
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text.removesuffix("```")
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


CHARACTER_FIELDS = (
    "name",
    "personality",
    "speech_style",
    "appearance",
    "backstory",
)

CHARACTER_FIELD_LABELS = {
    "name": "名字",
    "personality": "性格",
    "speech_style": "说话风格",
    "appearance": "外貌",
    "backstory": "背景故事",
}


async def generate_character_options(
    description: str,
    selected: dict[str, str],
    field: str,
    api_key: str,
    provider_name: str,
    **provider_kwargs,
) -> list[str]:
    """Generate four context-consistent choices for one character field."""
    if field not in CHARACTER_FIELDS:
        raise ValueError(f"Unknown character field: {field}")
    context_lines = [f"用户描述：{description}"]
    for key in CHARACTER_FIELDS:
        if key == field:
            break
        value = selected.get(key, "")
        if value:
            context_lines.append(
                f"{CHARACTER_FIELD_LABELS[key]}：{value}")
    instruction = (
        "你是角色设定设计师。根据已有设定，为指定属性生成4个彼此不同、"
        "且与上下文一致的中文候选项。不得修改已有设定。"
        "只输出 JSON：{\"options\":[\"...\",\"...\",\"...\",\"...\"]}。"
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                "\n".join(context_lines)
                + f"\n待生成属性：{CHARACTER_FIELD_LABELS[field]}"
            ),
        },
    ]
    from .provider import create_provider

    provider = create_provider(provider_name)
    provider.init_client(api_key, **provider_kwargs)
    text, _ = await provider.generate(
        messages,
        model=provider_kwargs["model"],
        max_tokens=1600,
        temperature=0.85,
    )
    data = _extract_json(text)
    options = data.get("options", [])
    if not isinstance(options, list):
        raise ValueError("AI did not return an option list")
    result = [str(option).strip() for option in options if str(option).strip()]
    if len(result) != 4 or len(set(result)) != 4:
        raise ValueError("AI did not return four distinct options")
    return result

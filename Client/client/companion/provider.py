"""AI Provider 抽象层 — 支持 Gemini 和 DeepSeek API

provider 字段值:
  "gemini"   → Google Gemini (google-genai SDK)
  "deepseek" → DeepSeek (OpenAI-compatible SDK)
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import AsyncIterator, Any

_log = logging.getLogger(__name__)

_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?:sk-|gsk_)[0-9A-Za-z_-]{16,}"),
    re.compile(r"Bearer\s+[0-9A-Za-z._-]{16,}", re.IGNORECASE),
)


def redact_sensitive_text(value: object, *secrets: str) -> str:
    """Remove API credentials before text reaches UI or logs."""
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text

# ── 通用工具声明（provider 无关） ──

TOOL_SCHEMAS: list[dict] = [
    {"name": "look_self", "description": "查看主人自己的资料 (名字/等级/经验/金币/称号/位置)",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "look_world_chat",
     "description": "查看世界公聊最近的消息",
     "parameters": {"type": "object", "properties": {
         "count": {"type": "integer", "description": "条数 (默认 10, 最多 50)"},
     }}},
    {"name": "look_room_chat",
     "description": "查看主人当前所在游戏房间的最近聊天",
     "parameters": {"type": "object", "properties": {
         "count": {"type": "integer", "description": "条数 (默认 10, 最多 50)"},
     }}},
    {"name": "look_online", "description": "查看当前在线的玩家列表",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "look_friends", "description": "查看主人的好友列表与在线状态",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "look_notifications",
     "description": "查看最近的系统通知",
     "parameters": {"type": "object", "properties": {
         "count": {"type": "integer", "description": "条数 (默认 10)"},
     }}},
    {"name": "look_dm_partners",
     "description": "列出当前客户端会话中有私聊消息的玩家",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "look_game",
     "description": "按需查看主人当前游戏的完整可见进程；仅在确实想了解比赛时调用",
     "parameters": {"type": "object", "properties": {}}},
    {
        "name": "look_messages",
        "description": "查询当前客户端会话的消息投影，可指定范围、私聊对象和数量。",
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {"type": "string",
                          "description": "查询范围: 'world' (公聊) / 'room' (房间聊天) / 'dm' (私聊)。默认 'dm'"},
                "peer": {"type": "string",
                         "description": "scope=dm 时按对话对象过滤；空表示不限"},
                "limit": {"type": "integer",
                          "description": "最多条数 (默认 10, 最多 50)"},
            },
        },
    },
]

COMPANION_REPLY_TOOL: dict = {
    "name": "deliver_companion_reply",
    "description": (
        "提交这一轮唯一的最终回复。只能调用一次；不要在字段中添加星号、"
        "换行或第二组动作与台词。"
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "maxLength": 80,
                "pattern": "^[^*\\r\\n]*$",
                "description": (
                    "可选的一段第三人称动作、表情或心理描写；不含星号和换行。"
                ),
            },
            "speech": {
                "type": "string",
                "maxLength": 300,
                "pattern": "^[^*\\r\\n]*$",
                "description": (
                    "一个连续的说话段落，最多三句；不含动作、星号和换行。"
                ),
            },
        },
        "required": ["action", "speech"],
    },
}


class ToolCall:
    """统一的工具调用结果"""
    __slots__ = ("name", "args")

    def __init__(self, name: str, args: dict | None = None):
        self.name = name
        self.args = args or {}


class AIProvider(ABC):
    """AI 提供商抽象基类"""

    @abstractmethod
    def init_client(self, api_key: str, **kwargs):
        """初始化客户端"""

    @abstractmethod
    async def generate(self, messages: list[dict], *, model: str,
                       max_tokens: int, temperature: float) -> tuple[str, int]:
        """非流式生成，返回 (文本, token用量)"""


    @abstractmethod
    async def validate_key(self, api_key: str, **kwargs) -> tuple[bool, str]:
        """验证 API Key，返回 (有效, 错误信息)"""

    @abstractmethod
    async def list_models(self, api_key: str, **kwargs) -> list[dict]:
        """列举可用模型，返回 [{name, display, desc, info}]"""


# ── Google Gemini Provider ──

class GoogleProvider(AIProvider):
    """Google Gemini (google-genai SDK)"""

    def __init__(self):
        self._client = None

    def init_client(self, api_key: str, **kwargs):
        try:
            from google import genai
            self._client = genai.Client(api_key=api_key)
        except Exception:
            self._client = None

    async def generate(self, messages: list[dict], *, model: str,
                       max_tokens: int, temperature: float) -> tuple[str, int]:
        from google.genai import types
        system, contents = _to_gemini_contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        resp = await self._client.aio.models.generate_content(
            model=model, contents=contents, config=config,
        )
        candidates = getattr(resp, "candidates", None)
        if candidates and candidates[0].finish_reason and \
           candidates[0].finish_reason.name == "MAX_TOKENS":
            raise ValueError("描述过长，请精简后重试")
        usage = resp.usage_metadata
        tokens = usage.total_token_count if usage and usage.total_token_count else 0
        return (resp.text or ""), tokens


    async def stream_with_tools(
        self, messages: list[dict], *, model: str,
        max_tokens: int, temperature: float,
        tools: list[dict] | None,
        execute_tool,
        final_tool: dict | None = None,
        max_rounds: int = 3,
    ) -> AsyncIterator[str | ToolCall]:
        """流式生成 + 多轮工具调用循环"""
        from google.genai import types
        system, contents = _to_gemini_contents(messages)
        schemas = _schemas_with_final_tool(tools, final_tool)
        gemini_tools = _to_gemini_tools(schemas) if schemas else None
        tool_config = None
        if final_tool:
            tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="ANY",
                    allowed_function_names=[
                        str(schema["name"]) for schema in schemas
                    ],
                )
            )
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=temperature,
            tools=gemini_tools,
            tool_config=tool_config,
        )

        for _round in range(max_rounds + 1):
            response = await self._client.aio.models.generate_content_stream(
                model=model, contents=contents, config=config,
            )
            function_calls = []
            last_usage = 0

            async for chunk in response:
                usage, texts, calls = _read_gemini_tool_chunk(
                    chunk, final_tool is not None,
                )
                last_usage = usage or last_usage
                for text in texts:
                    yield text
                function_calls.extend(calls)

            if last_usage:
                yield f"\x00TOKENS:{last_usage}"  # 特殊标记传递 token 数

            if not function_calls:
                if final_tool:
                    raise ValueError("旅伴没有按要求提交结构化回复")
                return

            final_call = _find_final_tool_call(
                function_calls, final_tool, lambda call: call.name,
            )
            if final_call:
                yield ToolCall(
                    final_call.name,
                    dict(final_call.args or {}),
                )
                return

            _append_gemini_tool_results(
                contents, function_calls, tools, execute_tool, types,
            )
        raise ValueError("旅伴在工具调用上超过轮次限制")

    async def validate_key(self, api_key: str, **kwargs) -> tuple[bool, str]:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            await client.aio.models.generate_content(
                model="gemini-2.5-flash", contents="hi",
            )
            return (True, "")
        except Exception as e:
            return (False, redact_sensitive_text(e, api_key))

    async def list_models(self, api_key: str, **kwargs) -> list[dict]:
        from google import genai
        client = genai.Client(api_key=api_key)
        result = await client.aio.models.list()
        skip = {"embedding", "tts", "audio", "robotics", "image", "computer-use", "customtools"}
        models = []
        for m in result:
            name = m.name or ""
            lower = name.lower()
            if "gemini" not in lower:
                continue
            actions = getattr(m, "supported_actions", []) or []
            if "generateContent" not in actions:
                continue
            if any(k in lower for k in skip):
                continue
            short = name.removeprefix("models/")
            display = getattr(m, "display_name", "") or short
            desc = (getattr(m, "description", "") or "").split(".")[0].strip()
            inp = getattr(m, "input_token_limit", 0) or 0
            out = getattr(m, "output_token_limit", 0) or 0
            info = f"in:{inp // 1024}K out:{out // 1024}K" if inp else ""
            models.append({"name": short, "display": display, "desc": desc, "info": info})
        models.sort(key=lambda x: x["name"], reverse=True)
        return models

# ── OpenAI Compatible Provider ──

class OpenAIProvider(AIProvider):
    """OpenAI 兼容 (openai SDK) — 支持 ChatGPT / 豆包 / DeepSeek 等"""

    def __init__(self):
        self._client = None

    def init_client(self, api_key: str, **kwargs):
        base_url = kwargs.get("base_url") or None
        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        except Exception:
            self._client = None

    async def generate(self, messages: list[dict], *, model: str,
                       max_tokens: int, temperature: float) -> tuple[str, int]:
        oai_messages = _to_openai_messages(messages)
        resp = await self._client.chat.completions.create(
            model=model, messages=oai_messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        text = resp.choices[0].message.content or "" if resp.choices else ""
        tokens = resp.usage.total_tokens if resp.usage else 0
        return text, tokens


    async def stream_with_tools(
        self, messages: list[dict], *, model: str,
        max_tokens: int, temperature: float,
        tools: list[dict] | None,
        execute_tool,
        final_tool: dict | None = None,
        max_rounds: int = 3,
    ) -> AsyncIterator[str | ToolCall]:
        """流式生成 + 多轮工具调用循环"""
        oai_messages = _to_openai_messages(messages)
        schemas = _schemas_with_final_tool(tools, final_tool)
        oai_tools = _to_openai_tools(schemas) if schemas else None

        for _round in range(max_rounds + 1):
            kwargs: dict[str, Any] = dict(
                model=model, messages=oai_messages,
                max_tokens=max_tokens, temperature=temperature,
                stream=True, stream_options={"include_usage": True},
            )
            if oai_tools:
                kwargs["tools"] = oai_tools
            if final_tool:
                kwargs["tool_choice"] = "required"
                kwargs["extra_body"] = {
                    "thinking": {"type": "disabled"},
                }

            response = await self._client.chat.completions.create(**kwargs)
            pending_tc: dict[int, dict] = {}
            assistant_content = ""

            async for chunk in response:
                tokens, content = _read_openai_tool_chunk(chunk, pending_tc)
                if tokens:
                    yield f"\x00TOKENS:{tokens}"
                if content and not final_tool:
                    assistant_content += content
                    yield content

            if not pending_tc:
                if final_tool:
                    raise ValueError("旅伴没有按要求提交结构化回复")
                return

            final_call = _find_final_tool_call(
                list(pending_tc.values()),
                final_tool,
                lambda call: call["name"],
            )
            if final_call:
                args = _parse_final_tool_args(final_call["args_buf"])
                yield ToolCall(final_call["name"], args)
                return

            _append_openai_tool_results(
                oai_messages, pending_tc, assistant_content,
                tools, execute_tool,
            )
        raise ValueError("旅伴在工具调用上超过轮次限制")

    async def validate_key(self, api_key: str, **kwargs) -> tuple[bool, str]:
        base_url = kwargs.get("base_url") or None
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            # 先尝试列出模型作为轻量验证
            result = await client.models.list()
            if result.data:
                return (True, "")
            # 若 list 为空但没报错，也算通过
            return (True, "")
        except Exception as e:
            return (False, redact_sensitive_text(e, api_key))

    async def list_models(self, api_key: str, **kwargs) -> list[dict]:
        base_url = kwargs.get("base_url") or None
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        result = await client.models.list()
        models = []
        for m in result.data:
            models.append({
                "name": m.id,
                "display": m.id,
                "desc": "",
                "info": "",
            })
        models.sort(key=lambda x: x["name"])
        return models

# ── Helper functions ──

def _schemas_with_final_tool(
    tools: list[dict] | None,
    final_tool: dict | None,
) -> list[dict]:
    schemas = [*(tools or [])]
    if final_tool:
        schemas.append(final_tool)
    return schemas


def _require_known_tool(name: str, tools: list[dict] | None) -> None:
    if not tools or not any(schema["name"] == name for schema in tools):
        raise ValueError(f"旅伴调用了未知工具: {name}")


def _find_final_tool_call(calls, final_tool: dict | None, name_of):
    if not final_tool:
        return None
    final_calls = [
        call for call in calls
        if name_of(call) == final_tool["name"]
    ]
    if not final_calls:
        return None
    if len(calls) != 1:
        raise ValueError("旅伴一次提交了多个最终回复或混合工具调用")
    return final_calls[0]


def _read_gemini_tool_chunk(chunk, suppress_text: bool) -> tuple[int, list, list]:
    usage = chunk.usage_metadata
    tokens = usage.total_token_count if usage and usage.total_token_count else 0
    texts = []
    calls = []
    if not chunk.candidates:
        return tokens, texts, calls
    for part in chunk.candidates[0].content.parts or []:
        if part.text and not suppress_text:
            texts.append(part.text)
        elif part.function_call:
            calls.append(part.function_call)
    return tokens, texts, calls


def _append_gemini_tool_results(
    contents: list,
    function_calls: list,
    tools: list[dict] | None,
    execute_tool,
    types,
) -> None:
    model_parts = []
    response_parts = []
    for function_call in function_calls:
        _require_known_tool(function_call.name, tools)
        model_parts.append(types.Part(function_call=function_call))
        result = execute_tool(
            function_call.name, dict(function_call.args or {}),
        )
        response_parts.append(types.Part(
            function_response=types.FunctionResponse(
                name=function_call.name,
                response={"output": result},
            )
        ))
    contents.append(types.Content(role="model", parts=model_parts))
    contents.append(types.Content(role="user", parts=response_parts))


def _accumulate_openai_tool_calls(delta, pending_calls: dict[int, dict]) -> None:
    for tool_call in delta.tool_calls or []:
        index = tool_call.index
        if index not in pending_calls:
            pending_calls[index] = {
                "name": "",
                "args_buf": "",
                "id": tool_call.id or "",
            }
        pending = pending_calls[index]
        if tool_call.function and tool_call.function.name:
            pending["name"] = tool_call.function.name
        if tool_call.function and tool_call.function.arguments:
            pending["args_buf"] += tool_call.function.arguments
        if tool_call.id:
            pending["id"] = tool_call.id


def _read_openai_tool_chunk(
    chunk,
    pending_calls: dict[int, dict],
) -> tuple[int, str]:
    tokens = (
        chunk.usage.total_tokens
        if chunk.usage and chunk.usage.total_tokens
        else 0
    )
    if not chunk.choices:
        return tokens, ""
    delta = chunk.choices[0].delta
    _accumulate_openai_tool_calls(delta, pending_calls)
    return tokens, delta.content or ""


def _parse_tool_args(raw_args: str):
    if not raw_args:
        return {}
    try:
        return json.loads(raw_args)
    except Exception:
        return {}


def _parse_final_tool_args(raw_args: str) -> dict:
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        raise ValueError("旅伴提交了无效的回复结构") from exc
    if not isinstance(args, dict):
        raise ValueError("旅伴提交的回复结构不是对象")
    return args


def _append_openai_tool_results(
    messages: list[dict],
    pending_calls: dict[int, dict],
    assistant_content: str,
    tools: list[dict] | None,
    execute_tool,
) -> None:
    tool_calls = []
    for pending in pending_calls.values():
        _require_known_tool(pending["name"], tools)
        tool_calls.append({
            "id": pending["id"],
            "type": "function",
            "function": {
                "name": pending["name"],
                "arguments": pending["args_buf"],
            },
        })
    messages.append({
        "role": "assistant",
        "content": assistant_content or None,
        "tool_calls": tool_calls,
    })
    for pending in pending_calls.values():
        result = execute_tool(
            pending["name"], _parse_tool_args(pending["args_buf"]),
        )
        messages.append({
            "role": "tool",
            "tool_call_id": pending["id"],
            "content": result,
        })

def _to_gemini_contents(messages: list[dict]) -> tuple[str, list[dict]]:
    """messages → (system_instruction, gemini contents)"""
    system = ""
    contents = []
    for m in messages:
        role = m["role"]
        text = m["content"]
        if role == "system":
            system = text
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": text}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": text}]})
    return system, contents


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """统一 messages 格式 → OpenAI messages"""
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def _to_gemini_tools(schemas: list[dict]) -> list:
    """TOOL_SCHEMAS → Gemini Tool 格式"""
    from google.genai import types
    decls = []
    for s in schemas:
        decls.append(types.FunctionDeclaration(
            name=s["name"],
            description=s["description"],
            parameters_json_schema=s.get("parameters") or {},
        ))
    return [types.Tool(function_declarations=decls)]


def _to_openai_tools(schemas: list[dict]) -> list[dict]:
    """TOOL_SCHEMAS → OpenAI tools 格式"""
    tools = []
    for s in schemas:
        params = s.get("parameters") or {"type": "object", "properties": {}}
        if not params.get("type"):
            params = {"type": "object", "properties": {}}
        tools.append({
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": params,
            },
        })
    return tools


# ── 工厂函数 ──

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

_PROVIDERS = {
    "gemini": GoogleProvider,
    "deepseek": OpenAIProvider,
}

PROVIDER_NAMES = {
    "gemini": "Gemini",
    "deepseek": "DeepSeek",
}


def create_provider(name: str) -> AIProvider:
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"Unknown provider: {name!r}. Available: {list(_PROVIDERS)}")
    return cls()


def provider_kwargs(name: str) -> dict[str, str]:
    """Return the fixed connection settings for a supported provider."""
    if name == "deepseek":
        return {"base_url": DEEPSEEK_BASE_URL}
    return {}

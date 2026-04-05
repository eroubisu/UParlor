"""AI Provider 抽象层 — 支持 Google Gemini 和 OpenAI 兼容 API

provider 字段值:
  "google"  → Google Gemini (google-genai SDK)
  "openai"  → OpenAI 兼容 (openai SDK, 支持豆包/DeepSeek/ChatGPT 等)
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, Any

_log = logging.getLogger(__name__)

# ── 通用工具声明（provider 无关） ──

TOOL_SCHEMAS: list[dict] = [
    {"name": "look_chat", "description": "查看聊天室最近的公共聊天消息", "parameters": {}},
    {"name": "look_online", "description": "查看当前在线的用户列表", "parameters": {}},
    {"name": "look_inventory", "description": "查看玩家的背包物品和金币", "parameters": {}},
    {"name": "look_game_room", "description": "查看当前游戏房间的状态、玩家和进度", "parameters": {}},
    {"name": "look_player_status", "description": "查看玩家的详细状态信息", "parameters": {}},
    {"name": "look_around", "description": "环顾四周，了解当前位置、在线用户和游戏房间情况", "parameters": {}},
    {"name": "look_friends", "description": "查看好友列表和在线状态", "parameters": {}},
    {
        "name": "look_dm",
        "description": "查看私聊消息。不指定 peer 时返回所有私聊对话概览，指定 peer 时返回与该用户的最近聊天记录",
        "parameters": {
            "type": "object",
            "properties": {
                "peer": {"type": "string", "description": "对方用户名，留空则返回所有私聊概览"},
                "count": {"type": "integer", "description": "查看条数，默认10，最多30"},
            },
        },
    },
    {"name": "look_notifications", "description": "查看系统通知", "parameters": {}},
]


class ToolCall:
    """统一的工具调用结果"""
    __slots__ = ("name", "args")

    def __init__(self, name: str, args: dict | None = None):
        self.name = name
        self.args = args or {}


class StreamResult:
    """一次流式生成的结果"""
    __slots__ = ("text", "tool_calls", "tokens")

    def __init__(self):
        self.text = ""
        self.tool_calls: list[ToolCall] = []
        self.tokens = 0


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
    async def stream(self, messages: list[dict], *, model: str,
                     max_tokens: int, temperature: float,
                     tools: list[dict] | None = None,
                     ) -> AsyncIterator[str | ToolCall]:
        """流式生成，yield 文本块或 ToolCall。最后一个 yield 可能是 int (token用量)。"""
        yield  # type: ignore

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

    async def stream(self, messages: list[dict], *, model: str,
                     max_tokens: int, temperature: float,
                     tools: list[dict] | None = None,
                     ) -> AsyncIterator[str | ToolCall]:
        from google.genai import types
        system, contents = _to_gemini_contents(messages)
        gemini_tools = _to_gemini_tools(tools) if tools else None
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=temperature,
            tools=gemini_tools,
        )
        response = await self._client.aio.models.generate_content_stream(
            model=model, contents=contents, config=config,
        )
        last_usage = 0
        async for chunk in response:
            usage = chunk.usage_metadata
            if usage and usage.total_token_count:
                last_usage = usage.total_token_count
            if not chunk.candidates:
                continue
            for part in chunk.candidates[0].content.parts or []:
                if part.text:
                    yield part.text
                elif part.function_call:
                    yield ToolCall(part.function_call.name, dict(part.function_call.args or {}))
        if last_usage:
            yield last_usage  # type: ignore

    async def stream_with_tools(
        self, messages: list[dict], *, model: str,
        max_tokens: int, temperature: float,
        tools: list[dict] | None,
        execute_tool,
        max_rounds: int = 3,
    ) -> AsyncIterator[str]:
        """流式生成 + 多轮工具调用循环"""
        from google.genai import types
        system, contents = _to_gemini_contents(messages)
        gemini_tools = _to_gemini_tools(tools) if tools else None
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=temperature,
            tools=gemini_tools,
        )

        for _round in range(max_rounds + 1):
            response = await self._client.aio.models.generate_content_stream(
                model=model, contents=contents, config=config,
            )
            function_calls = []
            last_usage = 0

            async for chunk in response:
                usage = chunk.usage_metadata
                if usage and usage.total_token_count:
                    last_usage = usage.total_token_count
                if not chunk.candidates:
                    continue
                for part in chunk.candidates[0].content.parts or []:
                    if part.text:
                        yield part.text
                    elif part.function_call:
                        function_calls.append(part.function_call)

            if last_usage:
                yield f"\x00TOKENS:{last_usage}"  # 特殊标记传递 token 数

            if not function_calls or not tools:
                return

            model_parts = []
            response_parts = []
            for fc in function_calls:
                model_parts.append(types.Part(function_call=fc))
                result = execute_tool(fc.name, dict(fc.args or {}))
                response_parts.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"output": result},
                    )
                ))
            contents.append(types.Content(role="model", parts=model_parts))
            contents.append(types.Content(role="user", parts=response_parts))

    async def validate_key(self, api_key: str, **kwargs) -> tuple[bool, str]:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            await client.aio.models.generate_content(
                model="gemini-2.5-flash", contents="hi",
            )
            return (True, "")
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                return (True, "")
            return (False, msg)

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

    @property
    def ready(self) -> bool:
        return self._client is not None


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

    async def stream(self, messages: list[dict], *, model: str,
                     max_tokens: int, temperature: float,
                     tools: list[dict] | None = None,
                     ) -> AsyncIterator[str | ToolCall]:
        oai_messages = _to_openai_messages(messages)
        kwargs: dict[str, Any] = dict(
            model=model, messages=oai_messages,
            max_tokens=max_tokens, temperature=temperature,
            stream=True, stream_options={"include_usage": True},
        )
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
        response = await self._client.chat.completions.create(**kwargs)
        # 累积 tool_call 片段
        pending_tc: dict[int, dict] = {}  # index → {name, args_buf}
        async for chunk in response:
            if chunk.usage and chunk.usage.total_tokens:
                yield chunk.usage.total_tokens  # type: ignore
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in pending_tc:
                        pending_tc[idx] = {"name": "", "args_buf": ""}
                    if tc.function and tc.function.name:
                        pending_tc[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        pending_tc[idx]["args_buf"] += tc.function.arguments
        # yield 完整的 tool calls
        for info in pending_tc.values():
            args = {}
            if info["args_buf"]:
                try:
                    args = json.loads(info["args_buf"])
                except Exception:
                    pass
            yield ToolCall(info["name"], args)

    async def stream_with_tools(
        self, messages: list[dict], *, model: str,
        max_tokens: int, temperature: float,
        tools: list[dict] | None,
        execute_tool,
        max_rounds: int = 3,
    ) -> AsyncIterator[str]:
        """流式生成 + 多轮工具调用循环"""
        oai_messages = _to_openai_messages(messages)
        oai_tools = _to_openai_tools(tools) if tools else None

        for _round in range(max_rounds + 1):
            kwargs: dict[str, Any] = dict(
                model=model, messages=oai_messages,
                max_tokens=max_tokens, temperature=temperature,
                stream=True, stream_options={"include_usage": True},
            )
            if oai_tools:
                kwargs["tools"] = oai_tools

            response = await self._client.chat.completions.create(**kwargs)
            pending_tc: dict[int, dict] = {}
            assistant_content = ""

            async for chunk in response:
                if chunk.usage and chunk.usage.total_tokens:
                    yield f"\x00TOKENS:{chunk.usage.total_tokens}"
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    assistant_content += delta.content
                    yield delta.content
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in pending_tc:
                            pending_tc[idx] = {"name": "", "args_buf": "", "id": tc.id or ""}
                        if tc.function and tc.function.name:
                            pending_tc[idx]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            pending_tc[idx]["args_buf"] += tc.function.arguments
                        if tc.id:
                            pending_tc[idx]["id"] = tc.id

            if not pending_tc or not oai_tools:
                return

            # 构建 assistant message with tool_calls
            tc_list = []
            for info in pending_tc.values():
                tc_list.append({
                    "id": info["id"],
                    "type": "function",
                    "function": {"name": info["name"], "arguments": info["args_buf"]},
                })
            oai_messages.append({
                "role": "assistant",
                "content": assistant_content or None,
                "tool_calls": tc_list,
            })

            # 执行工具并添加结果
            for info in pending_tc.values():
                args = {}
                if info["args_buf"]:
                    try:
                        args = json.loads(info["args_buf"])
                    except Exception:
                        pass
                result = execute_tool(info["name"], args)
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": info["id"],
                    "content": result,
                })

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
            msg = str(e)
            if "429" in msg or "rate" in msg.lower():
                return (True, "")
            return (False, msg)

    async def list_models(self, api_key: str, **kwargs) -> list[dict]:
        base_url = kwargs.get("base_url") or None
        try:
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
        except Exception:
            return []

    @property
    def ready(self) -> bool:
        return self._client is not None


# ── Helper functions ──

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

_PROVIDERS = {
    "google": GoogleProvider,
    "openai": OpenAIProvider,
}

PROVIDER_NAMES = {
    "google": "Google Gemini",
    "openai": "OpenAI 兼容",
}


def create_provider(name: str) -> AIProvider:
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"Unknown provider: {name!r}. Available: {list(_PROVIDERS)}")
    return cls()

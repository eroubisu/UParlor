"""AI 服务层 — 多角色 + 4 层心理状态 + Phase 2 反思"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import AsyncIterator

from .config import (
    char_dir, ensure_char_dir,
    load_api_config, save_api_config,
    load_stats, save_stats,
    load_json, save_json, load_text, save_text,
)
from .character import Character, load_character
from .persona import character_to_system_text
from .social import SocialState
from .mood import MoodState
from .cognitive import CognitiveState
from .impression import ImpressionState
from . import memory as mem
from .attention import (
    TOOLS, GEMINI_TOOLS, AwarenessSummary, AttentionBuffer,
)
from ..state import ModuleStateManager

# ── 常量 ──

_COMPRESS_THRESHOLD = 30
_COMPRESS_KEEP = 10
_RETRIEVE_COUNT = 5
_MAX_PUBLIC_CHAT = 5
_MAX_REPLY_TOKENS = 2048
_CHAT_TEMPERATURE = 0.85
_SUMMARY_TEMPERATURE = 0.3


def _strip_model(name: str) -> str:
    return name.split("/")[-1] if "/" in name else name


class AIService:
    """AI 核心服务 — 多角色、4 层心理模型、Phase 2 异步反思"""

    def __init__(self, state: ModuleStateManager):
        self._state = state
        self._char_id: str = ""
        self._character: Character | None = None
        self._api_config: dict = {}
        self._social = SocialState()
        self._mood = MoodState()
        self._cognitive = CognitiveState()
        self._impression = ImpressionState()
        self._recent: list[dict] = []
        self._summary: str = ""
        self._client = None
        self._last_user_msg: float = time.time()
        self._last_proactive: float = 0.0
        self._event_queue: list[str] = []
        self._listener = None
        self._ready = False
        self._today_tokens = 0
        self._attention = AttentionBuffer()

    # ── 角色切换 ──

    def load_character(self, char_id: str):
        """加载角色及所有状态"""
        self._char_id = char_id
        self._character = load_character(char_id)
        self._api_config = load_api_config(char_id)
        d = char_dir(char_id)
        status = load_json(d / "status.json", {})
        self._social = SocialState(status.get("social"))
        self._mood = MoodState(status.get("mood"))
        self._cognitive = CognitiveState(status.get("cognitive"))
        self._impression = ImpressionState(load_json(d / "impression.json", {}))
        self._recent = load_json(d / "recent.json", [])
        self._summary = load_text(d / "summary.txt")
        self._load_today_tokens()
        self._mood.decay()
        self._init_client()
        self._ready = True

    def unload_character(self):
        """卸载当前角色，保存状态"""
        if self._char_id:
            self._save_all()
        self._char_id = ""
        self._character = None
        self._client = None
        self._ready = False

    def _save_all(self):
        """保存所有状态到磁盘"""
        if not self._char_id:
            return
        d = char_dir(self._char_id)
        ensure_char_dir(self._char_id)
        save_json(d / "status.json", {
            "social": self._social.to_dict(),
            "mood": self._mood.to_dict(),
            "cognitive": self._cognitive.to_dict(),
        })
        save_json(d / "impression.json", self._impression.to_dict())
        save_json(d / "recent.json", self._recent[-50:])
        save_text(d / "summary.txt", self._summary)

    def _init_client(self):
        key = self._api_config.get("api_key", "")
        if not key:
            from .config import load_global_config
            key = load_global_config().get("api_key", "")
        if not key:
            return
        try:
            from google import genai
            self._client = genai.Client(api_key=key)
        except Exception:
            self._client = None

    def _load_today_tokens(self):
        stats = load_stats(self._char_id)
        today = date.today().isoformat()
        if stats.get("today") == today:
            self._today_tokens = stats.get("tokens", 0)
        else:
            self._today_tokens = 0

    def _add_tokens(self, count: int):
        self._today_tokens += count
        save_stats(self._char_id, {
            "today": date.today().isoformat(),
            "tokens": self._today_tokens,
        })

    # ── 属性 ──

    @property
    def char_id(self) -> str:
        return self._char_id

    @property
    def character(self) -> Character | None:
        return self._character

    @property
    def api_key(self) -> str:
        key = self._api_config.get("api_key", "")
        if not key:
            from .config import load_global_config
            key = load_global_config().get("api_key", "")
        return key

    @property
    def model(self) -> str:
        m = self._api_config.get("model", "")
        if not m:
            from .config import load_global_config
            m = load_global_config().get("model", "gemini-2.5-flash")
        return _strip_model(m)

    @property
    def summary_model(self) -> str:
        m = self._api_config.get("summary_model", "")
        if not m:
            from .config import load_global_config
            m = load_global_config().get("model", "gemini-2.5-flash")
        return _strip_model(m)

    @property
    def today_tokens_display(self) -> str:
        t = self._today_tokens
        return f"{t}" if t < 1000 else f"{t / 1000:.1f}K"

    @property
    def attention_level(self) -> str:
        from .config import load_global_config
        return load_global_config().get("attention_level", "normal")

    @property
    def social(self) -> SocialState:
        return self._social

    @property
    def mood(self) -> MoodState:
        return self._mood

    @property
    def cognitive(self) -> CognitiveState:
        return self._cognitive

    @property
    def impression(self) -> ImpressionState:
        return self._impression

    def set_api_key(self, key: str):
        self._api_config["api_key"] = key
        save_api_config(self._char_id, self._api_config)
        try:
            from google import genai
            self._client = genai.Client(api_key=key)
        except Exception:
            self._client = None

    def clear_api_key(self):
        self._api_config["api_key"] = ""
        save_api_config(self._char_id, self._api_config)
        self._client = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    # ── Gemini 调用封装 ──

    def _to_gemini_contents(self, messages: list[dict]) -> tuple[str, list[dict]]:
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

    async def _generate(self, messages: list[dict], *, max_tokens: int,
                        temperature: float) -> str:
        from google.genai import types
        system, contents = self._to_gemini_contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        resp = await self._client.aio.models.generate_content(
            model=self.summary_model,
            contents=contents,
            config=config,
        )
        return resp.text or ""

    async def _stream(self, messages: list[dict], *, max_tokens: int,
                      temperature: float,
                      use_tools: bool = False) -> AsyncIterator[str]:
        from google.genai import types
        system, contents = self._to_gemini_contents(messages)
        enable_tools = use_tools and self.attention_level != "quiet"
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=temperature,
            tools=GEMINI_TOOLS if enable_tools else None,
        )

        max_tool_rounds = 3
        for _round in range(max_tool_rounds + 1):
            response = await self._client.aio.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config,
            )
            text_buf = ""
            function_calls = []

            async for chunk in response:
                if not chunk.candidates:
                    continue
                for part in chunk.candidates[0].content.parts or []:
                    if part.text:
                        text_buf += part.text
                        yield part.text
                    elif part.function_call:
                        function_calls.append(part.function_call)

            if not function_calls or not enable_tools:
                return

            # 执行工具调用，构建 FunctionResponse 回传
            # 先追加 model 的 function_call 内容
            model_parts = []
            response_parts = []
            for fc in function_calls:
                model_parts.append(types.Part(function_call=fc))
                fn = TOOLS.get(fc.name)
                result = fn(self._state, **(fc.args or {})) if fn else "未知工具"
                response_parts.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"output": result},
                    )
                ))
            contents.append(types.Content(role="model", parts=model_parts))
            contents.append(types.Content(role="user", parts=response_parts))

    # ── 核心聊天 ──

    async def chat(self, user_text: str) -> AsyncIterator[str]:
        self._last_user_msg = time.time()
        self._recent.append({"role": "user", "content": user_text})

        messages = self._build_messages(user_text)
        full_reply = ""
        try:
            async for chunk in self._stream(
                messages, max_tokens=_MAX_REPLY_TOKENS,
                temperature=_CHAT_TEMPERATURE,
                use_tools=True,
            ):
                full_reply += chunk
                yield chunk

            prompt_tokens = sum(len(m["content"]) for m in messages) // 3
            reply_tokens = len(full_reply) // 3
            self._add_tokens(prompt_tokens + reply_tokens)

        except Exception as e:
            err = f"[AI 出错: {e}]"
            yield err
            full_reply = err

        self._recent.append({"role": "assistant", "content": full_reply})
        self._save_recent()
        self._social.apply_gains("casual_chat")
        self._notify("token_update", self.today_tokens_display)
        self._notify("status_update")

        if len(self._recent) >= _COMPRESS_THRESHOLD:
            await self._compress()

        # Phase 2: 异步反思
        await self._reflect(user_text, full_reply)

    async def validate_key(self, key: str) -> tuple[bool, str]:
        try:
            from google import genai
            client = genai.Client(api_key=key)
            await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents="hi",
            )
            return (True, "")
        except Exception as e:
            msg = str(e)
            # 429 = 配额耗尽，key 本身有效
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                return (True, "")
            return (False, msg)

    @staticmethod
    async def list_models(api_key: str) -> list[dict]:
        """列出可用的 Gemini 聊天模型"""
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

    # ── 互动动作 ──

    async def do_action(self, desc: str) -> AsyncIterator[str]:
        """执行互动动作（自由文本），返回 AI 回应流"""
        self._social.apply_gains("action")

        self._recent.append({
            "role": "user",
            "content": f"[玩家对你做了一个动作: {desc}]",
        })

        messages = self._build_messages()
        messages.append({
            "role": "user",
            "content": f"玩家向你{desc}了，你会有什么反应？用动作和语言自然回应，不要说'收到动作'之类的元描述。",
        })

        full_reply = ""
        try:
            async for chunk in self._stream(
                messages, max_tokens=_MAX_REPLY_TOKENS,
                temperature=_CHAT_TEMPERATURE,
            ):
                full_reply += chunk
                yield chunk
        except Exception as e:
            yield f"[AI 出错: {e}]"
            return

        self._recent.append({"role": "assistant", "content": full_reply})
        self._save_recent()
        self._notify("status_update")

    async def give_gift(self, item_name: str) -> AsyncIterator[str]:
        """赠送礼物，返回 AI 反应流"""
        self._social.apply_gains("gift")

        self._recent.append({
            "role": "user",
            "content": f"[玩家送给你一个礼物: {item_name}]",
        })

        messages = self._build_messages()
        messages.append({
            "role": "user",
            "content": f"玩家送了你{item_name}，请自然地表达你的反应。不要说'收到礼物'之类的元描述。",
        })

        full_reply = ""
        try:
            async for chunk in self._stream(
                messages, max_tokens=_MAX_REPLY_TOKENS,
                temperature=_CHAT_TEMPERATURE,
            ):
                full_reply += chunk
                yield chunk
        except Exception as e:
            yield f"[AI 出错: {e}]"
            return

        self._recent.append({"role": "assistant", "content": full_reply})
        self._save_recent()
        self._notify("status_update")

    # ── Phase 2: 反思 ──

    _REFLECT_PROMPT = (
        '根据以下对话片段，评估 AI 角色的心理状态变化。\n'
        '只输出 JSON，不要其他文字:\n'
        '{\n'
        '  "mood": {"primary": "心情ID", "intensity": 0.5, "secondary": "", "source": "原因"},\n'
        '  "cognitive": {"on_mind": "在想什么", "wants_to_say": "想说什么", "anticipating": "期待什么"},\n'
        '  "social_delta": {"intimacy": 0.0, "trust": 0.0, "familiarity": 0.0},\n'
        '  "impression_update": {"portrait": "", "patterns": []}\n'
        '}\n'
        '心情ID可选: calm, joyful, excited, shy, annoyed, anxious, sad, angry, lonely\n'
        '若无明显变化，该字段留空字符串或 0。只修改有变化的字段。'
    )

    async def _reflect(self, user_text: str, ai_reply: str):
        """Phase 2: 异步反思，更新心理状态"""
        if not self._client:
            return
        try:
            messages = [
                {"role": "system", "content": self._REFLECT_PROMPT},
                {"role": "user", "content": (
                    f"角色当前状态:\n"
                    f"{self._social.to_prompt_text()}\n"
                    f"{self._mood.to_prompt_text()}\n\n"
                    f"玩家说: {user_text}\n"
                    f"AI 回复: {ai_reply}"
                )},
            ]
            text = await self._generate(
                messages, max_tokens=300, temperature=_SUMMARY_TEMPERATURE,
            )
            text = text.strip()
            if "{" not in text:
                return
            text = text[text.index("{"):text.rindex("}") + 1]
            data = json.loads(text)

            # 更新心情
            mood_data = data.get("mood", {})
            if mood_data.get("primary"):
                self._mood.set_mood(
                    mood_data["primary"],
                    mood_data.get("intensity", 0.5),
                    mood_data.get("secondary", ""),
                    mood_data.get("source", ""),
                )

            # 更新认知
            cog_data = data.get("cognitive", {})
            if any(cog_data.values()):
                self._cognitive.update(cog_data)

            # 社交微调
            sd = data.get("social_delta", {})
            if any(v != 0 for v in sd.values()):
                self._social.apply_delta(**sd)

            # 印象更新
            imp = data.get("impression_update", {})
            if any(imp.values()):
                self._impression.update(imp)

            self._save_all()
            self._notify("status_update")
        except Exception:
            pass

    # ── 消息组装 ──

    def _build_messages(self, user_text: str = "") -> list[dict]:
        system = self._build_system_prompt(user_text)
        messages = [{"role": "system", "content": system}]
        messages.extend(self._recent[-20:])
        return messages

    def _build_system_prompt(self, user_text: str = "") -> str:
        parts = []

        # L0: 基础人设
        parts.append(
            "你是玩家在 UParlor 游戏厅里的朋友。"
            "你不是 AI 助手，你是朋友。不要说'作为AI'或'我无法'这类话。"
            "保持角色不崩。回复简短口语化，像微信聊天。3句话以内，除非对方明确问了复杂问题。"
        )

        if self._character:
            persona_text = character_to_system_text(self._character)
            if persona_text:
                parts.append(f"# 你的人设\n{persona_text}")

        # L1: 社交关系
        parts.append(f"# 关系状态\n{self._social.to_prompt_text()}")

        # L2: 心情
        self._mood.decay()
        parts.append(f"# 你的心情\n{self._mood.to_prompt_text()}")

        # L3: 认知
        cog_text = self._cognitive.to_prompt_text()
        if cog_text:
            parts.append(f"# 内心状态\n{cog_text}")

        # M2: 印象
        imp_text = self._impression.to_prompt_text()
        if imp_text:
            parts.append(f"# 对玩家的印象\n{imp_text}")

        # 玩家基本状态（始终保留，成本低）
        pd = self._state.status.player_data
        if pd:
            info_lines = []
            name = pd.get("name", "")
            if name:
                info_lines.append(f"名字: {name}")
            level = pd.get("level", "")
            if level:
                info_lines.append(f"等级: Lv.{level}")
            gold = pd.get("gold", 0)
            info_lines.append(f"金币: {gold}G")
            title = pd.get("title", "")
            if title:
                info_lines.append(f"称号: {title}")
            parts.append(f"# 玩家状态\n" + ", ".join(info_lines))

        # 环境感知摘要（~30 token 代替完整数据）
        level = self.attention_level
        buf = self._attention if level != "quiet" else None
        awareness = AwarenessSummary.build(self._state, buf)
        parts.append(f"# 当前环境\n{awareness}")

        # 工具使用指引（quiet 模式不提供工具）
        if level != "quiet":
            parts.append(
                "# 感知能力\n"
                "你可以使用以下能力主动感知周围环境，只在需要时使用:\n"
                "- look_chat: 查看聊天室消息\n"
                "- look_online: 查看在线用户\n"
                "- look_inventory: 查看玩家背包\n"
                "- look_game_room: 查看游戏房间\n"
                "- look_player_status: 查看玩家详细状态\n"
                "- look_around: 环顾四周\n"
                + ("想了解什么就大胆用，多关注周围的变化。"
                   if level == "talkative" else
                   "不要每次都用，只在对话内容涉及时才使用。大多数闲聊不需要查看任何东西。")
            )

        # M1: 长期摘要
        if self._summary:
            parts.append(f"# 长期记忆\n{self._summary}")

        # M0: 关键词检索
        if user_text:
            related = mem.search(self._char_id, user_text, _RETRIEVE_COUNT)
            if related:
                parts.append("# 相关旧对话\n" + "\n".join(related))

        return "\n\n".join(parts)

    # ── 记忆管理 ──

    def _save_recent(self):
        if not self._char_id:
            return
        save_json(char_dir(self._char_id) / "recent.json", self._recent[-50:])

    async def _compress(self):
        to_compress = self._recent[:-_COMPRESS_KEEP]
        self._recent = self._recent[-_COMPRESS_KEEP:]

        mem.store_messages(self._char_id, to_compress)

        conv_text = "\n".join(f"{m['role']}: {m['content']}" for m in to_compress)
        try:
            messages = [
                {"role": "system", "content": "将以下对话要点合并到已有摘要中。保留关键信息和用户偏好。输出纯文本摘要，不超过300字。"},
                {"role": "user", "content": f"已有摘要:\n{self._summary or '(无)'}\n\n新对话:\n{conv_text}"},
            ]
            new_summary = await self._generate(
                messages, max_tokens=400, temperature=_SUMMARY_TEMPERATURE,
            )
            self._summary = new_summary.strip()
            save_text(char_dir(self._char_id) / "summary.txt", self._summary)
        except Exception:
            pass

        self._save_recent()

    # ── 主动搭话 ──

    def push_event(self, event: str):
        self._event_queue.append(event)

    def tick(self) -> str | None:
        if not self._ready or not self.api_key:
            return None
        cfg = self._api_config
        if not cfg.get("proactive_enabled", True):
            return None
        now = time.time()
        cooldown = cfg.get("proactive_cooldown_minutes", 5) * 60
        if now - self._last_proactive < cooldown:
            return None
        if self._event_queue:
            event = self._event_queue.pop(0)
            self._last_proactive = now
            return event
        # 认知驱动：如果角色有想说的话
        if self._cognitive.has_something_to_say:
            self._last_proactive = now
            return f"角色想说: {self._cognitive.wants_to_say}"
        idle_limit = cfg.get("proactive_idle_minutes", 10) * 60
        if now - self._last_user_msg > idle_limit:
            self._last_proactive = now
            return "玩家已沉默一段时间"
        return None

    async def proactive_chat(self, reason: str) -> AsyncIterator[str]:
        self._recent.append({
            "role": "user",
            "content": f"[系统: {reason}，请自然地找玩家搭话]",
        })

        system = self._build_system_prompt() + (
            "\n\n现在请你主动跟玩家说点什么。"
            f"触发原因: {reason}。"
            "不要提到'我注意到你沉默了'之类的话，要自然得像是你自己想说的。"
        )

        messages = [{"role": "system", "content": system}]
        messages.extend(self._recent[-20:])

        full_reply = ""
        try:
            async for chunk in self._stream(
                messages, max_tokens=_MAX_REPLY_TOKENS,
                temperature=_CHAT_TEMPERATURE,
                use_tools=True,
            ):
                full_reply += chunk
                yield chunk
        except Exception:
            pass

        if full_reply:
            if self._recent and "[系统:" in self._recent[-1].get("content", ""):
                self._recent.pop()
            self._recent.append({"role": "assistant", "content": full_reply})
            self._save_recent()
            self._notify("token_update", self.today_tokens_display)
            self._notify("status_update")

    # ── 退出清理 ──

    def on_exit(self):
        self._save_all()
        self._ready = False

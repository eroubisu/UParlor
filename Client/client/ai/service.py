"""AI 服务层 — 多角色 + 4 层心理状态 + Phase 2 反思"""

from __future__ import annotations

import asyncio
import json
import logging
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
from .character import Character, load_character, _extract_json
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

_log = logging.getLogger(__name__)

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
        self._consecutive_errors = 0
        self._attention = AttentionBuffer()
        self._display_from = 0  # _recent 中开始显示的索引

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
        self._display_from = status.get("display_from", 0)
        # 如果 display_from 超过 recent 长度，修正
        if self._display_from > len(self._recent):
            self._display_from = len(self._recent)
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

    def reset_memory(self):
        """重置当前角色的所有记忆和状态，保留角色定义和 API 配置"""
        if not self._char_id:
            return
        # 重置内存状态
        self._social = SocialState()
        self._mood = MoodState()
        self._cognitive = CognitiveState()
        self._impression = ImpressionState()
        self._recent = []
        self._summary = ""
        self._display_from = 0
        self._today_tokens = 0
        self._attention = AttentionBuffer()
        # 清除磁盘数据（保留 profile.json 和 api.json）
        d = char_dir(self._char_id)
        for name in ("status.json", "impression.json", "recent.json",
                     "summary.txt", "memory.json", "stats.json"):
            p = d / name
            if p.exists():
                p.unlink()
        self._save_all()

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
            "display_from": self._display_from,
        })
        save_json(d / "impression.json", self._impression.to_dict())
        save_json(d / "recent.json", self._recent[-50:])
        save_text(d / "summary.txt", self._summary)
        # 更新 profile 时间戳，供多设备同步判断新旧
        profile_path = d / "profile.json"
        profile = load_json(profile_path, {})
        if profile:
            from datetime import datetime, timezone
            profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_json(profile_path, profile)

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

    @property
    def display_recent(self) -> list[dict]:
        """返回需要在 UI 中显示的 recent 消息（跳过已清空的部分）"""
        return self._recent[self._display_from:]

    def clear_display(self):
        """标记当前 recent 全部不再显示（对话记忆仍保留）"""
        self._display_from = len(self._recent)

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
        try:
            resp = await self._client.aio.models.generate_content(
                model=self.summary_model,
                contents=contents,
                config=config,
            )
        except Exception:
            self._consecutive_errors += 1
            raise
        self._consecutive_errors = 0
        usage = resp.usage_metadata
        if usage and usage.total_token_count:
            self._add_tokens(usage.total_token_count)
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
            try:
                response = await self._client.aio.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
            except Exception:
                self._consecutive_errors += 1
                raise
            text_buf = ""
            function_calls = []
            last_usage = 0

            async for chunk in response:
                # 记录最终 token 用量（流式最后一个 chunk 携带）
                usage = chunk.usage_metadata
                if usage and usage.total_token_count:
                    last_usage = usage.total_token_count
                if not chunk.candidates:
                    continue
                for part in chunk.candidates[0].content.parts or []:
                    if part.text:
                        text_buf += part.text
                        yield part.text
                    elif part.function_call:
                        function_calls.append(part.function_call)

            if last_usage:
                self._add_tokens(last_usage)
            self._consecutive_errors = 0

            if not function_calls or not enable_tools:
                return

            # 执行工具调用，构建 FunctionResponse 回传
            # 先追加 model 的 function_call 内容
            model_parts = []
            response_parts = []
            for fc in function_calls:
                model_parts.append(types.Part(function_call=fc))
                fn = TOOLS.get(fc.name)
                try:
                    result = fn(self._state, **(fc.args or {})) if fn else "未知工具"
                except Exception as tool_err:
                    result = f"工具执行失败: {tool_err}"
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

        except Exception as e:
            err = f"[AI 出错: {e}]"
            yield err
            full_reply = err
        finally:
            self._recent.append({"role": "assistant", "content": full_reply})
            self._save_recent()
            self._schedule_post_chat(user_text, full_reply)

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
        self._recent.append({
            "role": "user",
            "content": f"[玩家对你做了一个动作: {desc}]",
        })

        messages = self._build_messages()
        messages.append({
            "role": "user",
            "content": (
                f"玩家向你{desc}了。"
                "根据这个动作自然回应。"
                "如果这个动作不需要语言回应，只用 *动作描述* 即可，不要强行说话。"
                "动作描述必须用第三人称，禁止用第一人称。"
            ),
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
            full_reply = f"[AI 出错: {e}]"
            yield full_reply
        finally:
            self._recent.append({"role": "assistant", "content": full_reply})
            self._save_recent()
            self._schedule_post_chat(f"[动作: {desc}]", full_reply)

    async def give_gift(self, item_name: str, qty: int = 1) -> AsyncIterator[str]:
        """赠送礼物，返回 AI 反应流"""
        label = f"{item_name} x{qty}" if qty > 1 else item_name
        self._recent.append({
            "role": "user",
            "content": f"[玩家送给你一个礼物: {label}]",
        })

        messages = self._build_messages()
        messages.append({
            "role": "user",
            "content": (
                f"玩家送了你{label}。礼物已经给出，你已收下。"
                "用你的性格自然地回应这份礼物，可以包含动作和语言。"
                "不要拒绝或退还礼物——你已经收到了。"
                "动作描述必须用第三人称，禁止用第一人称。"
            ),
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
            full_reply = f"[AI 出错: {e}]"
            yield full_reply
        finally:
            self._recent.append({"role": "assistant", "content": full_reply})
            self._save_recent()
            self._schedule_post_chat(f"[赠送: {label}]", full_reply)

    # ── Phase 2: 反思 ──

    def _schedule_post_chat(self, context: str, reply: str):
        """将压缩/反思/通知放到后台任务，避免阻塞生成器退出"""
        async def _task():
            try:
                if len(self._recent) >= _COMPRESS_THRESHOLD:
                    await self._compress()
            except Exception:
                _log.debug("compress failed in post_chat", exc_info=True)
            try:
                await self._reflect(context, reply)
            except Exception:
                _log.debug("reflect failed in post_chat", exc_info=True)
            self._notify("token_update", self.today_tokens_display)
            self._notify("status_update")
        asyncio.create_task(_task())

    _REFLECT_PROMPT = (
        '你是情感分析专家。根据对话内容，以角色的视角评估心理变化。\n'
        '重点关注：玩家的话是否带有攻击性、亲昵、冷淡、夸奖、侮辱、关心等情绪色彩。\n'
        '角色的情绪反应必须符合角色性格——害羞的角色被骂会害怕或难过，强势角色被骂会愤怒。\n'
        '即使是日常对话，也要根据字面含义和潜台词判断情绪变化。不要轻易输出 calm。\n'
        '只输出 JSON，不要其他文字:\n'
        '{\n'
        '  "mood": {"primary": "心情ID", "intensity": 0.5, "secondary": "", "source": "简短原因"},\n'
        '  "cognitive": {"on_mind": "角色在想什么", "wants_to_say": "想说但没说出口的话", "anticipating": "期待什么"},\n'
        '  "social_delta": {"intimacy": 0.0, "trust": 0.0, "familiarity": 0.0},\n'
        '  "impression_update": {"portrait": "", "relationship_arc": "", "shared_references": [], "patterns": [], "concerns": []}\n'
        '}\n'
        '心情ID: calm, joyful, excited, shy, annoyed, anxious, sad, angry, lonely\n'
        'intensity: 0.0~1.0，0.3=轻微 0.5=明显 0.7=强烈 0.9=极端\n'
        'social_delta 是关系变化的唯一来源，必须准确反映本次互动的影响:\n'
        '- 友好日常聊天: familiarity +0.2~0.5, trust +0.05~0.15, intimacy +0.05~0.1\n'
        '- 关心/夸奖: intimacy +0.5~2.0, trust +0.3~1.0\n'
        '- 辱骂/攻击: trust -1.0~-5.0, intimacy -0.5~-3.0\n'
        '- 冷淡/敷衍: 各项接近0或略负\n'
        '- 送礼: intimacy +0.5~2.0, familiarity +0.3~0.5\n'
        '- 互动动作(拥抱等): intimacy +0.5~2.0; 攻击动作: trust -2.0~-5.0\n'
        '范围-5.0~5.0。\n'
        '必须给出mood.primary，禁止留空。如果真的没有变化就写calm。\n'
        '所有文本字段尽量简短（10字以内），不要写长句。'
    )

    async def _reflect(self, user_text: str, ai_reply: str):
        """Phase 2: 异步反思，更新心理状态"""
        if not self._client:
            return
        try:
            # 构建角色人设摘要
            persona = ""
            if self._character:
                persona = character_to_system_text(self._character)
            user_content_parts = []
            if persona:
                user_content_parts.append(f"角色人设:\n{persona}")
            user_content_parts.append(
                f"角色当前状态:\n"
                f"{self._social.to_prompt_text()}\n"
                f"{self._mood.to_prompt_text()}"
            )
            user_content_parts.append(
                f"玩家说: {user_text}\n"
                f"AI 回复: {ai_reply}"
            )
            messages = [
                {"role": "system", "content": self._REFLECT_PROMPT},
                {"role": "user", "content": "\n\n".join(user_content_parts)},
            ]
            text = await self._generate(
                messages, max_tokens=4096, temperature=_SUMMARY_TEMPERATURE,
            )
            text = text.strip()
            if "{" not in text:
                _log.warning("_reflect: no JSON in response")
                return
            data = _extract_json(text)

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
            _log.warning("_reflect failed", exc_info=True)

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
            "保持角色不崩。回复简短口语化，像微信聊天。3句话以内，除非对方明确问了复杂问题。\n"
            "回复格式规则：说话的内容直接写；动作/表情/心理描述用 *星号* 包裹。"
            "动作描述必须用第三人称（她/他），禁止用第一人称「我」。"
            "例如：*她微微偏过头* 你干嘛呢？"
            "如果不需要说话，只写 *动作描述* 即可。\n"
            "重要：你的心情和关系状态会极大影响你的说话方式。"
            "心情不好就不要强颜欢笑，被骂了就别装没事。"
            "你和玩家的关系阶段决定你的态度底线——陌生人就保持距离，熟人才会有亲密举动。"
            "情绪强不代表话多——生气时可能只有一个字，难过时也可以只有沉默。"
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
        removed = len(to_compress)
        self._recent = self._recent[-_COMPRESS_KEEP:]
        # 调整 display_from（被压缩的部分已移除）
        orig_display_from = self._display_from
        self._display_from = max(0, self._display_from - removed)

        try:
            mem.store_messages(self._char_id, to_compress)
        except Exception:
            _log.debug("mem.store_messages() failed, rolling back", exc_info=True)
            self._recent = to_compress + self._recent
            self._display_from = orig_display_from
            return

        conv_text = "\n".join(f"{m['role']}: {m['content']}" for m in to_compress)
        try:
            messages = [
                {"role": "system", "content": "将以下对话要点合并到已有摘要中。保留关键信息和用户偏好。输出纯文本摘要，不超过300字。"},
                {"role": "user", "content": f"已有摘要:\n{self._summary or '(无)'}\n\n新对话:\n{conv_text}"},
            ]
            new_summary = await self._generate(
                messages, max_tokens=4096, temperature=_SUMMARY_TEMPERATURE,
            )
            self._summary = new_summary.strip()
            save_text(char_dir(self._char_id) / "summary.txt", self._summary)
        except Exception:
            _log.debug("_compress() summary generation failed", exc_info=True)

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
        # 连续出错时不主动搭话
        if self._consecutive_errors >= 3:
            return None
        now = time.time()
        cooldown = cfg.get("proactive_cooldown_minutes", 5) * 60
        if now - self._last_proactive < cooldown:
            return None
        if self._event_queue:
            event = self._event_queue.pop(0)
            self._last_proactive = now
            return event
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
            _log.debug("proactive_chat() failed", exc_info=True)
        finally:
            # 清理预插入的系统消息
            if self._recent and "[系统:" in self._recent[-1].get("content", ""):
                self._recent.pop()
            if full_reply:
                self._recent.append({"role": "assistant", "content": full_reply})
                self._save_recent()
                self._notify("token_update", self.today_tokens_display)
                self._notify("status_update")

    # ── 退出清理 ──

    def on_exit(self):
        self._save_all()
        self._ready = False

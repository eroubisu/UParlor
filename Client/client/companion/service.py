"""AI 旅伴服务层 — 多角色 + 4 层心理状态 + 内联反思

与旧版差异:
- 移除 panel 多设备同步回调（_sync_cb / set_sync_callback / _request_sync）
- 移除 export/import_all_chars 的远端同步钩子
- listener 接口改为 Agent 直接订阅（status_update / token_update）

state 参数是由主线程捕获的账号标记投影，后台任务不遍历 UI State。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any, AsyncIterator

from .config import (
    char_dir, ensure_char_dir,
    load_global_config, load_player_config,
    load_stats, save_stats,
    load_json, save_json, load_text, save_text,
)
from .character import Character, load_character, _extract_json
from .persona import character_to_system_text, format_companion_reply
from .social import SocialState
from .mood import MoodState
from .mood import MOODS
from .cognitive import CognitiveState
from .impression import ImpressionState
from . import memory as mem
from .attention import TOOLS, AwarenessSummary, AttentionBuffer
from .provider import (
    COMPANION_REPLY_TOOL,
    TOOL_SCHEMAS,
    AIProvider,
    ToolCall,
    create_provider,
    provider_kwargs,
)

_log = logging.getLogger(__name__)

# ── 常量 ──

_COMPRESS_THRESHOLD = 12
_COMPRESS_KEEP = 4
_RETRIEVE_COUNT = 5
_MAX_REPLY_TOKENS = 2048
_MAX_STATE_EVALUATION_TOKENS = 512
_CHAT_TEMPERATURE = 0.85
_STATE_EVALUATION_TEMPERATURE = 0.1
_SUMMARY_TEMPERATURE = 0.3
_HISTORY_BUDGET = {"talkative": 3000, "normal": 1800, "quiet": 800}
_HISTORY_MAX = {"talkative": 20, "normal": 16, "quiet": 8}
_HISTORY_MIN = 4

# ── 提示词模板 ──

_PROMPTS_PATH = Path(__file__).parent / "data" / "prompts.json"
try:
    with open(_PROMPTS_PATH, "r", encoding="utf-8") as _f:
        _PROMPTS: dict[str, str] = json.load(_f)
except (FileNotFoundError, json.JSONDecodeError):
    _PROMPTS = {}


def _strip_model(name: str) -> str:
    return name.rsplit("/", 1)[-1] if "/" in name else name


class AIService:
    """AI 核心服务 — 多角色、4 层心理模型、内联反思"""

    def __init__(self, state: Any):
        self._state = state
        self._active = True
        self._char_id: str = ""
        self._character: Character | None = None
        self._social = SocialState()
        self._mood = MoodState()
        self._cognitive = CognitiveState()
        self._impression = ImpressionState()
        self._recent: list[dict] = []
        self._summary: str = ""
        self._provider: AIProvider | None = None
        self._last_user_msg: float = time.time()
        self._last_proactive: float = 0.0
        self._ready = False
        self._today_tokens = 0
        self._consecutive_errors = 0
        self._attention = AttentionBuffer()
        self._event_lock = threading.Lock()
        self._pending_events: deque[str] = deque(maxlen=10)
        self._display_from = 0
        self._compressing: bool = False
        self._cached_static_prompt: str = ""

    # ── 角色切换 ──

    def rebind_state(self, state: Any) -> None:
        """替换为主线程捕获的当前账号 State 投影。"""
        if self._active:
            self._state = state

    def load_character(self, char_id: str):
        """加载角色及所有状态"""
        self._char_id = char_id
        self._character = load_character(char_id)
        d = char_dir(char_id)
        status = load_json(d / "status.json", {})
        self._social = SocialState(status.get("social"))
        self._mood = MoodState(status.get("mood"))
        self._cognitive = CognitiveState(status.get("cognitive"))
        self._impression = ImpressionState(load_json(d / "impression.json", {}))
        self._recent = load_json(d / "recent.json", [])
        self._display_from = status.get("display_from", 0)
        legacy_system_indexes = [
            index for index, item in enumerate(self._recent)
            if item.get("role") == "user"
            and str(item.get("content", "")).startswith("[系统:")
        ]
        if legacy_system_indexes:
            removed_before_display = sum(
                index < self._display_from for index in legacy_system_indexes)
            self._recent = [
                item for index, item in enumerate(self._recent)
                if index not in set(legacy_system_indexes)
            ]
            self._display_from = max(
                0, self._display_from - removed_before_display)
            self._save_recent()
        self._display_from = min(self._display_from, len(self._recent))
        self._summary = load_text(d / "summary.txt")
        self._load_today_tokens()
        self._mood.decay()
        self._init_provider()
        self._build_static_prompt()
        self._ready = True

    def _save_all(self):
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

    # ── Provider / 配置 ──

    def _init_provider(self):
        key = self.api_key
        if not key:
            return
        provider_name = self.provider_name
        try:
            self._provider = create_provider(provider_name)
            self._provider.init_client(key, **provider_kwargs(provider_name))
        except Exception as exc:
            from .provider import redact_sensitive_text
            _log.debug(
                "init_provider failed: %s",
                redact_sensitive_text(exc, key),
            )
            self._provider = None

    def _load_today_tokens(self):
        stats = load_stats()
        today = date.today().isoformat()
        if stats.get("today") == today:
            self._today_tokens = sum(stats.get("models", {}).values())
        else:
            self._today_tokens = 0

    def _add_tokens(self, count: int, model: str = ""):
        model = model or self.model
        stats = load_stats()
        today = date.today().isoformat()
        if stats.get("today") != today:
            stats = {"today": today, "models": {}}
        models = stats.setdefault("models", {})
        models[model] = models.get(model, 0) + count
        save_stats(stats)
        self._today_tokens = sum(models.values())

    # ── 属性 ──

    @property
    def char_id(self) -> str:
        return self._char_id

    @property
    def character(self) -> Character | None:
        return self._character

    def visible_history(self) -> list[dict[str, str]]:
        """Return the persisted conversation segment shown in the chat UI."""
        history = self._recent[self._display_from:]
        visible = []
        for item in history:
            if (
                    item.get("role") not in ("user", "assistant")
                    or not item.get("content")):
                continue
            entry = {
                "role": str(item.get("role", "")),
                "content": str(item.get("content", "")),
            }
            if item.get("time"):
                entry["time"] = str(item["time"])
            visible.append(entry)
        return visible

    def clear_visible_history(self) -> None:
        """Hide the current chat projection without deleting companion memory."""
        self._display_from = len(self._recent)
        self._save_all()

    def discard_proactive_reply(self, text: str) -> bool:
        """Remove a proactive reply that was superseded before UI delivery."""
        if not self._recent:
            return False
        latest = self._recent[-1]
        if (
                latest.get("role") != "assistant"
                or latest.get("origin") != "proactive"
                or latest.get("content") != text):
            return False
        self._recent.pop()
        self._save_recent()
        return True

    def public_status(self) -> dict:
        """Return the relationship and mood fields intended for the player."""
        self._mood.decay()
        return {
            "relationship": {
                "stage": self._social.stage_label,
                "intimacy": round(self._social.intimacy),
                "trust": round(self._social.trust),
                "familiarity": round(self._social.familiarity),
            },
            "mood": {
                "primary": MOODS.get(
                    self._mood.primary, self._mood.primary),
                "secondary": MOODS.get(
                    self._mood.secondary, self._mood.secondary),
                "intensity": round(self._mood.intensity * 100),
                "source": self._mood.source,
            },
        }

    @property
    def api_key(self) -> str:
        return load_global_config().get("api_key", "")

    @property
    def provider_name(self) -> str:
        return load_global_config().get("provider", "gemini")

    @property
    def model(self) -> str:
        return _strip_model(load_global_config().get("model", ""))

    @property
    def summary_model(self) -> str:
        return self.model

    @property
    def attention_level(self) -> str:
        return load_player_config().get("attention_level", "normal")

    @property
    def activity_level(self) -> str:
        """主动行为强度：quiet / normal / talkative"""
        return load_player_config().get("activity_level", "normal")

    # ── 工具调用 ──

    def _execute_tool(self, name: str, args: dict) -> str:
        if not self._active:
            return "会话已结束"
        fn = TOOLS.get(name)
        try:
            return fn(self._state, **args) if fn else "未知工具"
        except Exception as e:
            from .provider import redact_sensitive_text
            return f"工具执行失败: {redact_sensitive_text(e, self.api_key)}"

    async def _generate(self, messages: list[dict], *, max_tokens: int,
                        temperature: float) -> str:
        try:
            text, tokens = await self._provider.generate(
                messages, model=self.summary_model,
                max_tokens=max_tokens, temperature=temperature,
            )
        except Exception:
            self._consecutive_errors += 1
            raise
        if not self._active:
            return ""
        self._consecutive_errors = 0
        if tokens:
            self._add_tokens(tokens, model=self.summary_model)
        return text

    _TOKEN_PREFIX = "\x00TOKENS:"

    async def _stream(self, messages: list[dict], *, max_tokens: int,
                      temperature: float,
                      use_tools: bool = False) -> AsyncIterator[str]:
        enable_tools = use_tools and self.attention_level != "quiet"
        tools = TOOL_SCHEMAS if enable_tools else None
        try:
            gen = self._provider.stream_with_tools(
                messages, model=self.model,
                max_tokens=max_tokens, temperature=temperature,
                tools=tools, execute_tool=self._execute_tool,
                final_tool=COMPANION_REPLY_TOOL,
            )
            async for chunk in gen:
                if not self._active:
                    break
                if isinstance(chunk, str) and chunk.startswith(self._TOKEN_PREFIX):
                    try:
                        count = int(chunk[len(self._TOKEN_PREFIX):])
                        self._add_tokens(count)
                    except ValueError:
                        pass
                elif isinstance(chunk, ToolCall):
                    if chunk.name != COMPANION_REPLY_TOOL["name"]:
                        raise ValueError(
                            f"旅伴提交了未知的最终回复工具: {chunk.name}"
                        )
                    yield format_companion_reply(chunk.args)
                else:
                    yield chunk
        except Exception:
            self._consecutive_errors += 1
            raise
        self._consecutive_errors = 0

    # ── 核心聊天 ──

    async def chat(self, user_text: str) -> AsyncIterator[str]:
        if not self._active:
            return
        self._last_user_msg = time.time()
        self._recent.append({
            "role": "user",
            "content": user_text,
            "time": datetime.now().strftime("%H:%M:%S"),
        })

        # The attention buffer still exposes these events to this reply.
        # Consuming the proactive queue prevents a second reply after chat.
        self._take_events()
        messages = self._build_messages(user_text)
        full_reply = ""
        generation_succeeded = True
        try:
            async for chunk in self._stream(
                messages, max_tokens=_MAX_REPLY_TOKENS,
                temperature=_CHAT_TEMPERATURE,
                use_tools=True,
            ):
                full_reply += chunk
                yield chunk
        except Exception as e:
            generation_succeeded = False
            from .provider import redact_sensitive_text
            safe_error = redact_sensitive_text(e, self.api_key)
            err = f"[AI 出错: {safe_error}]"
            yield err
            full_reply = err
            from . import llm_log
            llm_log.record("error", kind_inner="chat", message=safe_error)
        finally:
            if not self._active:
                return
            if full_reply:
                self._recent.append({
                    "role": "assistant",
                    "content": full_reply,
                    "time": datetime.now().strftime("%H:%M:%S"),
                })
            else:
                if self._recent and self._recent[-1].get("role") == "user":
                    self._recent.pop()
            self._save_recent()
            if full_reply and generation_succeeded:
                await self._evaluate_interaction(user_text, full_reply)
            # LLM 日志 (UPARLOR_LLM_LOG=1 启用)
            from . import llm_log
            if llm_log.is_enabled():
                llm_log.record(
                    "chat",
                    model=self.model,
                    user=user_text,
                    output=full_reply,
                    messages_count=len(messages),
                )
            if len(self._recent) >= _COMPRESS_THRESHOLD:
                try:
                    await self._compress()
                except Exception:
                    _log.debug("compress failed after chat", exc_info=True)

    # ── 消息组装 ──

    def _select_history(self) -> list[dict]:
        level = self.attention_level
        budget = _HISTORY_BUDGET.get(level, 1800)
        cap = _HISTORY_MAX.get(level, 16)
        selected: list[dict] = []
        cost = 0
        for msg in reversed(self._recent):
            c = len(msg.get("content", ""))
            if cost + c > budget and len(selected) >= _HISTORY_MIN:
                break
            selected.append(msg)
            cost += c
            if len(selected) >= cap:
                break
        selected.reverse()
        return selected

    def _build_messages(self, user_text: str = "") -> list[dict]:
        system = self._build_system_prompt(user_text)
        messages = [{"role": "system", "content": system}]
        messages.extend(self._select_history())
        return messages

    def _build_static_prompt(self):
        parts = []
        if _PROMPTS.get("identity"):
            parts.append(f"# 你是谁\n{_PROMPTS['identity']}")
        if _PROMPTS.get("expression"):
            parts.append(f"# 表达规则\n{_PROMPTS['expression']}")
        if _PROMPTS.get("emotion"):
            parts.append(f"# 情绪与关系原则\n{_PROMPTS['emotion']}")
        if self._character:
            persona_text = character_to_system_text(self._character)
            if persona_text:
                parts.append(f"# 你的人设\n{persona_text}")
        self._cached_static_prompt = "\n\n".join(parts)

    def _build_system_prompt(self, user_text: str = "") -> str:
        parts = [self._cached_static_prompt]

        parts.append(f"# 关系状态\n{self._social.to_prompt_text()}")

        self._mood.decay()
        parts.append(f"# 你的心情\n{self._mood.to_prompt_text()}")

        cog_text = self._cognitive.to_prompt_text()
        if cog_text:
            parts.append(f"# 内心状态\n{cog_text}")

        imp_text = self._impression.to_prompt_text()
        if imp_text:
            parts.append(f"# 对玩家的印象\n{imp_text}")

        # 玩家状态（duck-typed 安全访问）
        try:
            pd = getattr(self._state.status, "player_data", {}) or {}
        except Exception:
            pd = {}
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
            parts.append("# 玩家状态\n" + ", ".join(info_lines))

        level = self.attention_level
        buf = self._attention if level != "quiet" else None
        awareness = AwarenessSummary.build(self._state, buf)
        parts.append(f"# 当前环境\n{awareness}")

        if level != "quiet":
            guide = _PROMPTS.get(
                "tools_guide_active" if level == "talkative"
                else "tools_guide_normal", "")
            if guide:
                parts.append(f"# 感知能力\n{guide}")

        if self._summary:
            parts.append(f"# 长期记忆\n{self._summary}")

        if user_text and len(user_text) >= 4 and level != "quiet":
            related = mem.search(self._char_id, user_text, _RETRIEVE_COUNT)
            if related:
                parts.append("# 相关旧对话\n" + "\n".join(related))

        return "\n\n".join(parts)

    # ── 统一状态评估 ──

    async def _evaluate_interaction(
        self,
        interaction: str,
        reply: str,
    ) -> None:
        prompt = _PROMPTS.get("state_evaluation", "")
        if not prompt:
            _log.error("Companion state evaluation prompt is missing")
            return
        context = {
            "character": (
                character_to_system_text(self._character)
                if self._character is not None else ""
            ),
            "current_mood": self._mood.to_dict(),
            "current_relationship": self._social.to_dict(),
            "interaction": interaction,
            "reply": reply,
        }
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(context, ensure_ascii=False),
            },
        ]
        try:
            text, tokens = await self._provider.generate(
                messages,
                model=self.model,
                max_tokens=_MAX_STATE_EVALUATION_TOKENS,
                temperature=_STATE_EVALUATION_TEMPERATURE,
            )
            self._add_tokens(tokens)
            data = _extract_json(text)
        except Exception:
            _log.error("Companion state evaluation failed", exc_info=True)
            return
        self._apply_state_evaluation(data)

    def _apply_state_evaluation(self, data: dict):
        mood_data = data.get("mood", {})
        if mood_data.get("primary"):
            self._mood.set_mood(
                mood_data["primary"],
                mood_data.get("intensity", 0.5),
                mood_data.get("secondary", ""),
                mood_data.get("source", ""),
            )
        cog_data = data.get("cognitive", {})
        if any(cog_data.values()):
            self._cognitive.update(cog_data)
        sd = data.get("social_delta", {})
        if any(v != 0 for v in sd.values()):
            self._social.apply_delta(**sd)
        imp = data.get("impression_update", {})
        if any(imp.values()):
            self._impression.update(imp)
        self._save_all()

    # ── 记忆压缩 ──

    def _save_recent(self):
        if not self._char_id:
            return
        save_json(char_dir(self._char_id) / "recent.json", self._recent[-50:])

    async def _compress(self):
        if self._compressing:
            return
        self._compressing = True
        try:
            await self._do_compress()
        finally:
            self._compressing = False

    async def _do_compress(self):
        to_compress = self._recent[:-_COMPRESS_KEEP]
        removed = len(to_compress)
        self._recent = self._recent[-_COMPRESS_KEEP:]
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
            ctx = ""
            if self._character:
                ctx = f"角色: {self._character.name}, 性格: {self._character.personality}\n"
            messages = [
                {"role": "system", "content": _PROMPTS.get("compress", "")},
                {"role": "user", "content": f"{ctx}已有摘要:\n{self._summary or '(无)'}\n\n新对话:\n{conv_text}"},
            ]
            new_summary = await self._generate(
                messages, max_tokens=512, temperature=_SUMMARY_TEMPERATURE,
            )
            self._summary = new_summary.strip()
            save_text(char_dir(self._char_id) / "summary.txt", self._summary)
        except Exception:
            _log.debug("_compress() summary generation failed", exc_info=True)

        self._save_recent()

    # ── 主动搭话（事件队列 + 沉默触发，由 Agent 决策循环消费） ──

    _ACTIVE_WINDOW = 120
    # 不同活跃度对应的沉默搭话冷却（分钟）
    _ACTIVITY_COOLDOWN = {"quiet": 30, "normal": 10, "talkative": 3}
    _ACTIVITY_IDLE = {"quiet": 30, "normal": 10, "talkative": 5}
    _EVENT_COOLDOWN = 60

    def observe_event(self, summary: str) -> None:
        """Record an important event for the next proactive decision."""
        summary = summary.strip()
        if not summary:
            return
        with self._event_lock:
            self._pending_events.append(summary)
            self._attention.push(summary)

    def _take_events(self) -> list[str]:
        with self._event_lock:
            events = list(self._pending_events)
            self._pending_events.clear()
        return events

    def tick(self) -> str | None:
        """轮询返回是否应该主动搭话；返回 reason 字符串或 None"""
        if not self._ready or not self.api_key:
            return None
        if self._consecutive_errors >= 3:
            return None
        now = time.time()

        level = self.activity_level
        if now - self._last_proactive >= self._EVENT_COOLDOWN:
            events = self._take_events()
            if events:
                self._last_proactive = now
                return "；".join(events)

        if now - self._last_user_msg < self._ACTIVE_WINDOW:
            return None

        cooldown = self._ACTIVITY_COOLDOWN.get(level, 10) * 60
        if now - self._last_proactive < cooldown:
            return None
        idle_limit = self._ACTIVITY_IDLE.get(level, 10) * 60
        if now - self._last_user_msg > idle_limit:
            self._last_proactive = now
            return "玩家已沉默一段时间"
        return None

    async def proactive_chat(self, reason: str) -> AsyncIterator[str]:
        if not self._active:
            return

        proactive_text = _PROMPTS.get("proactive", "").format(reason=reason)
        system = self._build_system_prompt() + f"\n\n{proactive_text}"

        messages = [{"role": "system", "content": system}]
        messages.extend(self._select_history())

        full_reply = ""
        cancelled = False
        try:
            async for chunk in self._stream(
                messages, max_tokens=_MAX_REPLY_TOKENS,
                temperature=_CHAT_TEMPERATURE,
                use_tools=True,
            ):
                full_reply += chunk
                yield chunk
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as e:
            from .provider import redact_sensitive_text
            safe_error = redact_sensitive_text(e, self.api_key)
            _log.debug("proactive_chat() failed: %s", safe_error)
            from . import llm_log
            llm_log.record(
                "error", kind_inner="proactive", message=safe_error,
            )
        finally:
            if not self._active:
                return
            if full_reply and not cancelled:
                self._recent.append({
                    "role": "assistant",
                    "content": full_reply,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "origin": "proactive",
                })
                self._save_recent()
                await self._evaluate_interaction(reason, full_reply)
            from . import llm_log
            if llm_log.is_enabled():
                llm_log.record(
                    "proactive", model=self.model,
                    reason=reason, output=full_reply,
                )

    # ── 退出 ──

    def on_exit(self):
        if not self._active:
            return
        self._save_all()
        self._ready = False
        self._active = False

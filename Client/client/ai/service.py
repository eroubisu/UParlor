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
    load_api_config,
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
from .attention import TOOLS, AwarenessSummary, AttentionBuffer
from .provider import (
    TOOL_SCHEMAS, create_provider, AIProvider, PROVIDER_NAMES,
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
        self._provider: AIProvider | None = None
        self._last_user_msg: float = time.time()
        self._last_proactive: float = 0.0
        self._event_queue: list[str] = []
        self._listener = None
        self._ready = False
        self._today_tokens = 0
        self._consecutive_errors = 0
        self._attention = AttentionBuffer()
        self._display_from = 0  # _recent 中开始显示的索引
        self._sync_cb = None
        self._last_sync: float = 0.0
        self._pending_sync: bool = False
        self._pending_reflect: dict | None = None

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
        self._init_provider()
        self._ready = True

    def unload_character(self):
        """卸载当前角色，保存状态"""
        if self._char_id:
            self._save_all()
            self._force_sync()
        self._char_id = ""
        self._character = None
        self._provider = None
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
        self._request_sync()

    # ── 多端同步 ──

    def set_sync_callback(self, cb):
        """设置服务器同步回调（由面板注册）"""
        self._sync_cb = cb

    def _request_sync(self):
        """请求服务器同步（防抖 30 秒）"""
        now = time.time()
        if now - self._last_sync < 30:
            self._pending_sync = True
            return
        self._do_sync()

    def _do_sync(self):
        if self._sync_cb:
            try:
                self._sync_cb()
            except Exception:
                _log.debug("sync callback failed", exc_info=True)
        self._last_sync = time.time()
        self._pending_sync = False

    def _force_sync(self):
        """强制同步（退出/卸载时调用）"""
        if self._pending_sync or time.time() - self._last_sync > 5:
            self._do_sync()

    def _init_provider(self):
        key = self.api_key
        if not key:
            return
        provider_name = self.provider_name
        try:
            self._provider = create_provider(provider_name)
            kwargs = {}
            base_url = self._resolve_config("base_url", "")
            if base_url:
                kwargs["base_url"] = base_url
            self._provider.init_client(key, **kwargs)
        except Exception:
            self._provider = None

    def _load_today_tokens(self):
        stats = load_stats()
        today = date.today().isoformat()
        if stats.get("today") == today:
            self._today_tokens = stats.get("tokens", 0)
        else:
            self._today_tokens = 0

    def _add_tokens(self, count: int):
        self._today_tokens += count
        save_stats({
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
        from .config import load_global_config
        return load_global_config().get("api_key", "")

    @property
    def provider_name(self) -> str:
        return self._resolve_config("provider", "google")

    @property
    def model(self) -> str:
        m = self._resolve_config("model", "gemini-2.5-flash")
        return _strip_model(m)

    @property
    def summary_model(self) -> str:
        m = self._api_config.get("summary_model", "")
        if not m:
            m = self._resolve_config("model", "gemini-2.5-flash")
        return _strip_model(m)

    def _resolve_config(self, key: str, default: str = "") -> str:
        """角色级 → 全局级 配置瀑布查询"""
        val = self._api_config.get(key, "")
        if not val:
            from .config import load_global_config
            val = load_global_config().get(key, default)
        return val or default

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
        from .config import load_global_config, save_global_config
        cfg = load_global_config()
        cfg["api_key"] = key
        save_global_config(cfg)
        self._init_provider()

    def clear_api_key(self):
        from .config import load_global_config, save_global_config
        cfg = load_global_config()
        cfg["api_key"] = ""
        save_global_config(cfg)
        self._provider = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    # ── API 调用封装 ──

    def _execute_tool(self, name: str, args: dict) -> str:
        """执行工具调用"""
        fn = TOOLS.get(name)
        try:
            return fn(self._state, **args) if fn else "未知工具"
        except Exception as e:
            return f"工具执行失败: {e}"

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
        self._consecutive_errors = 0
        if tokens:
            self._add_tokens(tokens)
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
            )
            async for chunk in gen:
                if isinstance(chunk, str) and chunk.startswith(self._TOKEN_PREFIX):
                    try:
                        count = int(chunk[len(self._TOKEN_PREFIX):])
                        self._add_tokens(count)
                    except ValueError:
                        pass
                else:
                    yield chunk
        except Exception:
            self._consecutive_errors += 1
            raise
        self._consecutive_errors = 0

    # ── 核心聊天 ──

    async def chat(self, user_text: str) -> AsyncIterator[str]:
        self._last_user_msg = time.time()
        self._recent.append({"role": "user", "content": user_text})

        messages = self._build_messages(user_text)
        full_reply = ""
        try:
            async for chunk in self._stream_and_reflect(
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
            if self._pending_reflect:
                self._apply_reflect_data(self._pending_reflect)
                self._pending_reflect = None
            self._schedule_post_chat()

    async def validate_key(self, key: str) -> tuple[bool, str]:
        provider = create_provider(self.provider_name)
        kwargs: dict = {}
        base_url = self._resolve_config("base_url", "")
        if base_url:
            kwargs["base_url"] = base_url
        model = self.model
        if model:
            kwargs["model"] = model
        return await provider.validate_key(key, **kwargs)

    async def list_models(self, api_key: str) -> list[dict]:
        """列出可用模型"""
        provider = create_provider(self.provider_name)
        kwargs: dict = {}
        base_url = self._resolve_config("base_url", "")
        if base_url:
            kwargs["base_url"] = base_url
        return await provider.list_models(api_key, **kwargs)

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
            async for chunk in self._stream_and_reflect(
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
            if self._pending_reflect:
                self._apply_reflect_data(self._pending_reflect)
                self._pending_reflect = None
            self._schedule_post_chat()

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
            async for chunk in self._stream_and_reflect(
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
            if self._pending_reflect:
                self._apply_reflect_data(self._pending_reflect)
                self._pending_reflect = None
            self._schedule_post_chat()

    # ── Phase 2: 反思 ──

    def _schedule_post_chat(self):
        """将压缩/通知放到后台任务，避免阻塞生成器退出"""
        async def _task():
            try:
                if len(self._recent) >= _COMPRESS_THRESHOLD:
                    await self._compress()
            except Exception:
                _log.debug("compress failed in post_chat", exc_info=True)
            self._notify("token_update", self.today_tokens_display)
            self._notify("status_update")
        asyncio.create_task(_task())

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
                "- look_friends: 查看好友列表和在线状态\n"
                "- look_dm: 查看私聊消息（可看概览或指定人的对话）\n"
                "- look_notifications: 查看系统通知\n"
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

        # 内联反思指令
        parts.append(
            "# 内心反馈（必须）\n"
            "每次回复末尾必须附加隐藏标签，紧跟最后一个字符，不要换行。格式：\n"
            '<!--REFLECT:{"mood":{"primary":"心情ID","intensity":0.5,"source":"原因"},'
            '"cognitive":{"on_mind":"在想什么","wants_to_say":"","anticipating":""},'
            '"social_delta":{"intimacy":0,"trust":0,"familiarity":0},'
            '"impression_update":{"portrait":"","relationship_arc":""}}-->\n'
            "心情ID: calm/joyful/excited/shy/annoyed/anxious/sad/angry/lonely\n"
            "intensity: 0.0~1.0（0.3轻微 0.5明显 0.7强烈 0.9极端）\n"
            "social_delta 范围-5.0~5.0:\n"
            "- 友好日常: familiarity+0.2~0.5, trust+0.05~0.15, intimacy+0.05~0.1\n"
            "- 关心/夸奖: intimacy+0.5~2, trust+0.3~1\n"
            "- 辱骂/攻击: trust-1~-5, intimacy-0.5~-3\n"
            "- 冷淡/敷衍: 各项接近0或略负\n"
            "- 送礼: intimacy+0.5~2, familiarity+0.3~0.5\n"
            "- 互动动作(拥抱等): intimacy+0.5~2; 攻击: trust-2~-5\n"
            "根据角色性格真实反应，不要每次都calm。必须给出mood.primary。\n"
            "所有文本字段尽量简短（10字以内）。"
        )

        return "\n\n".join(parts)

    # ── 内联反思流式处理 ──

    _REFLECT_MARKER = "<!--REFLECT:"
    _REFLECT_MARKER_LEN = len(_REFLECT_MARKER)

    async def _stream_and_reflect(
        self, messages: list[dict], *, max_tokens: int,
        temperature: float, use_tools: bool = False,
    ) -> AsyncIterator[str]:
        """包装 _stream，实时检测并剥离 <!--REFLECT:...--> 标签。"""
        pending = ""
        self._pending_reflect = None
        in_tag = False
        tag_buf = ""

        async for chunk in self._stream(
            messages, max_tokens=max_tokens,
            temperature=temperature, use_tools=use_tools,
        ):
            if in_tag:
                tag_buf += chunk
                continue

            pending += chunk

            marker_pos = pending.find(self._REFLECT_MARKER)
            if marker_pos != -1:
                before = pending[:marker_pos].rstrip("\n")
                if before:
                    yield before
                tag_buf = pending[marker_pos:]
                in_tag = True
                pending = ""
                continue

            # 保留尾部可能是标签开头的部分（最多 MARKER_LEN-1 字符）
            safe = len(pending) - self._REFLECT_MARKER_LEN + 1
            if safe > 0:
                yield pending[:safe]
                pending = pending[safe:]

        # 流结束
        if in_tag and tag_buf:
            end = tag_buf.find("-->")
            if end != -1:
                json_str = tag_buf[self._REFLECT_MARKER_LEN:end]
                try:
                    self._pending_reflect = _extract_json(json_str)
                except Exception:
                    _log.debug("Failed to parse inline reflect JSON")
                after = tag_buf[end + 3:].strip()
                if after:
                    yield after
            else:
                yield tag_buf
        elif pending:
            yield pending

    def _apply_reflect_data(self, data: dict):
        """将内联反思数据应用到心理状态。"""
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
        self._notify("status_update")

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
            async for chunk in self._stream_and_reflect(
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
                if self._pending_reflect:
                    self._apply_reflect_data(self._pending_reflect)
                    self._pending_reflect = None
                self._notify("token_update", self.today_tokens_display)
                self._notify("status_update")

    # ── 退出清理 ──

    def on_exit(self):
        self._save_all()
        self._force_sync()
        self._ready = False

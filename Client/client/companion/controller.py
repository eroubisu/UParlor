"""CompanionController — 客户端进程内的旅伴生命周期管理 (chat-only 本地模块)。

核心特点 (与已删除的 CompanionAgent 完全不同):
- 不连服务器，不占账号；只是在主客户端进程里跑的本地模块
- 持有一个 AIService + 一个 AttentionBuffer
- 从主客户端 ModuleStateManager 捕获账号标记快照作为感知数据源
- 玩家登录后调 set_player(name) 切换到该玩家的私有目录 (角色/历史隔离)
- enabled=True 时启动后台 asyncio 线程跑 tick；enabled=False 时仅响应窗口对话

接口:
    ctrl = CompanionController.instance(state)
    ctrl.set_player("alice")            # 登录成功后调
    ctrl.set_enabled(True)              # 设置面板开关
    async for chunk in ctrl.chat(text): ...     # 窗口对话
    ctrl.shutdown()                     # App 退出
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, AsyncIterator, Callable

from . import config as cfg
from .attention import snapshot_state
from .provider import create_provider, provider_kwargs
from .service import AIService

_log = logging.getLogger(__name__)


# 后台 tick 周期 (秒)
_TICK_INTERVAL = 2.0


class CompanionController:
    """旅伴单例控制器。"""

    _instance: "CompanionController | None" = None

    @classmethod
    def instance(cls, state: Any | None = None) -> "CompanionController":
        if cls._instance is None:
            if state is None:
                raise RuntimeError("first instance() call must pass state")
            cls._instance = cls(state)
        elif state is not None and state is not cls._instance._state:
            cls._instance.rebind_state(state)
        return cls._instance

    def __init__(self, state: Any):
        self._state = state
        self._service: AIService | None = None
        self._player: str = ""
        self._generation = 0

        # 后台 loop (开关 ON 时启动)
        self._bg_loop: asyncio.AbstractEventLoop | None = None
        self._bg_thread: threading.Thread | None = None
        self._bg_tick_task: asyncio.Task | None = None
        self._bg_ready: threading.Event | None = None
        self._bg_running = False

        # 主动事件回调 (UI 注册，AI 想说话时收到通知)
        self._on_proactive: Callable[[str, int], None] | None = None
        self._proactive_lock = threading.Lock()
        self._proactive_revision = 0
        self._pending_proactive: tuple[int, str] | None = None

    # ── 玩家切换 ──

    def rebind_state(self, state: Any) -> None:
        """终止旧会话并绑定新的 State，即使用户名随后相同。"""
        if state is self._state:
            return
        self.clear_session()
        self._state = state

    def clear_session(self) -> None:
        """注销/换号时清除所有账号身份与异步工作。"""
        self._invalidate_pending_proactive()
        self._generation += 1
        self._stop_background()
        self._release_service()
        self._player = ""
        cfg.set_current_player("")

    def set_player(self, player_name: str):
        """登录成功后调用。切换到该玩家的私有目录并加载首选角色。"""
        player_name = (player_name or "").strip()
        if not player_name:
            return
        if player_name == self._player:
            return
        self._invalidate_pending_proactive()
        self._generation += 1
        self._stop_background()
        self._release_service()
        # 切换 player
        cfg.set_current_player(player_name)
        self._player = player_name
        # 按需启动
        if cfg.load_player_config().get("enabled"):
            self._ensure_service()
            self._start_background()

    @property
    def player(self) -> str:
        return self._player

    @property
    def generation(self) -> int:
        return self._generation

    # ── 状态查询 ──

    def is_enabled(self) -> bool:
        if not self._player:
            return False
        return bool(cfg.load_player_config().get("enabled", False))

    def is_running(self) -> bool:
        return self._bg_running

    def has_character(self) -> bool:
        from .character import list_characters
        return len(list_characters()) > 0

    def has_api_key(self) -> bool:
        return bool(cfg.load_global_config().get("api_key", ""))

    def is_ready(self) -> bool:
        config = cfg.load_global_config()
        return (
            self.has_api_key()
            and bool(config.get("model"))
            and self.has_character()
            and bool(self._player)
        )

    # ── 开关 ──

    def set_enabled(self, enabled: bool):
        if not self._player:
            return
        c = cfg.load_player_config()
        c["enabled"] = bool(enabled)
        cfg.save_player_config(c)
        if enabled:
            if self.is_ready():
                self._ensure_service()
                self._start_background()
        else:
            self._stop_background()

    def set_background_proactive(self, enabled: bool) -> None:
        if not self._player:
            return
        config = cfg.load_player_config()
        config["background_proactive"] = bool(enabled)
        cfg.save_player_config(config)
        self._stop_background()
        if enabled and self.is_enabled() and self.is_ready():
            self._ensure_service()
            self._start_background()

    # ── Service 访问 ──

    def get_service(self) -> AIService | None:
        """获取 AIService；首次访问时按需创建并加载首选角色。"""
        if self._service is None:
            self._ensure_service()
        return self._service

    def _ensure_service(self):
        if self._service is not None:
            return
        if not self._player:
            return
        service = AIService(snapshot_state(self._state, self._player))
        self._service = service
        # 加载首选角色 (player_config.last_character_id 或第一个)
        from .character import list_characters
        chars = list_characters()
        if not chars:
            return
        pc = cfg.load_player_config()
        prefer = pc.get("last_character_id", "")
        char_id = prefer if prefer in [c.id for c in chars] else chars[0].id
        try:
            self._service.load_character(char_id)
            pc["last_character_id"] = char_id
            cfg.save_player_config(pc)
        except Exception:
            _log.exception("load_character failed: %s", char_id)

    def _release_service(self) -> None:
        service = self._service
        self._service = None
        if service is None:
            return
        try:
            service.on_exit()
        except Exception:
            _log.exception("companion service shutdown failed")

    def load_character(self, char_id: str):
        """切换到指定角色。"""
        restart_background = self._bg_running
        if restart_background:
            self._stop_background()
        try:
            svc = self.get_service()
            if not svc:
                return
            svc.load_character(char_id)
            pc = cfg.load_player_config()
            pc["last_character_id"] = char_id
            cfg.save_player_config(pc)
        finally:
            if restart_background and self.is_enabled() and self.is_ready():
                self._start_background()

    def delete_character(self, char_id: str) -> None:
        """Delete a character and select a remaining character when possible."""
        from .character import delete_character, list_characters

        restart_background = self._bg_running
        if restart_background:
            self._stop_background()
        active_id = self._service.char_id if self._service else ""
        if active_id == char_id:
            self._release_service()
        delete_character(char_id)
        player_config = cfg.load_player_config()
        remaining = list_characters()
        if player_config.get("last_character_id") == char_id:
            player_config["last_character_id"] = (
                remaining[0].id if remaining else "")
            cfg.save_player_config(player_config)
        if remaining and self._service is None:
            self._ensure_service()
        if (
            restart_background
            and self.is_enabled()
            and self.is_ready()
        ):
            self._start_background()

    def observe_event(self, summary: str) -> None:
        """Forward one important main-thread event to the active companion."""
        if (
            not summary
            or not self.is_enabled()
            or not cfg.load_player_config().get("background_proactive", True)
            or not self.is_ready()
        ):
            return
        service = self.get_service()
        if service is None:
            return
        service.rebind_state(snapshot_state(self._state, self._player))
        service.observe_event(summary)

    def visible_history(self) -> list[dict[str, Any]]:
        service = self.get_service()
        if service is None or not service.char_id:
            return []
        return service.visible_history()

    def clear_visible_history(self) -> bool:
        service = self.get_service()
        if service is None or not service.char_id:
            return False
        service.clear_visible_history()
        return True

    def restore_visible_history(self) -> bool:
        service = self.get_service()
        if service is None or not service.char_id:
            return False
        return service.restore_visible_history()

    def add_record(self, text: str) -> None:
        self._state.cmd.add_line(text)

    def player_chat_sender(self) -> dict:
        return self._state.chat.sender(self._player)

    def public_status(self) -> dict:
        service = self.get_service()
        if service is None or not service.char_id:
            return {}
        return service.public_status()

    async def validate_api(
        self, provider_name: str, api_key: str,
    ) -> tuple[bool, str, list[dict]]:
        """Validate a draft provider/key pair and return its available models."""
        provider = create_provider(provider_name)
        kwargs = provider_kwargs(provider_name)
        valid, error = await provider.validate_key(api_key, **kwargs)
        if not valid:
            return False, error, []
        models = await provider.list_models(api_key, **kwargs)
        return True, "", models

    async def list_models(
        self, provider_name: str, api_key: str,
    ) -> list[dict]:
        provider = create_provider(provider_name)
        return await provider.list_models(
            api_key, **provider_kwargs(provider_name))

    async def generate_character_options(
        self,
        description: str,
        selected: dict[str, str],
        field: str,
    ) -> list[str]:
        from .character import generate_character_options

        config = cfg.load_global_config()
        provider_name = config["provider"]
        kwargs = provider_kwargs(provider_name)
        kwargs["model"] = config["model"]
        return await generate_character_options(
            description,
            selected,
            field,
            config["api_key"],
            provider_name,
            **kwargs,
        )

    def apply_api_config(
        self, provider_name: str, api_key: str, model: str = "",
    ) -> None:
        """Persist validated API settings and rebuild the active service."""
        config = cfg.load_global_config()
        config.update({
            "provider": provider_name,
            "api_key": api_key,
            "base_url": provider_kwargs(provider_name).get("base_url", ""),
            "model": model,
        })
        cfg.save_global_config(config)
        self.refresh_configuration()

    def set_model(self, model: str) -> None:
        config = cfg.load_global_config()
        config["model"] = model
        cfg.save_global_config(config)
        self.refresh_configuration()

    def refresh_configuration(self) -> None:
        """Recreate the service after provider, key, or model changes."""
        was_enabled = self.is_enabled()
        self._stop_background()
        self._release_service()
        if self._player and self.is_ready():
            self._ensure_service()
            if was_enabled:
                self._start_background()

    # ── UI 对话入口 (在主线程的 asyncio 中执行) ──

    async def chat(self, text: str) -> AsyncIterator[str]:
        self._invalidate_pending_proactive()
        restart_background = self._bg_running
        if restart_background:
            self._stop_background()
        generation = self._generation
        svc = self.get_service()
        try:
            if svc is None or not svc.char_id:
                yield "[未配置旅伴]"
                return
            svc.rebind_state(snapshot_state(self._state, self._player))
            async for chunk in svc.chat(text):
                if generation != self._generation or svc is not self._service:
                    break
                yield chunk
        finally:
            if (
                restart_background
                and generation == self._generation
                and svc is self._service
                and self.is_enabled()
                and self.is_ready()
            ):
                self._start_background()

    # ── UI 监听 ──

    @property
    def proactive_revision(self) -> int:
        with self._proactive_lock:
            return self._proactive_revision

    def set_on_proactive(
            self, cb: Callable[[str, int], None] | None):
        self._on_proactive = cb

    def _invalidate_pending_proactive(self) -> None:
        with self._proactive_lock:
            self._proactive_revision += 1
            pending = self._pending_proactive
            self._pending_proactive = None
        if pending and self._service is not None:
            self._service.discard_proactive_reply(pending[1])

    def deliver_proactive(
        self,
        text: str,
        revision: int,
        receiver: Callable[[str], None],
    ) -> None:
        """Deliver only if no player chat superseded this proactive reply."""
        with self._proactive_lock:
            if (
                    revision != self._proactive_revision
                    or self._pending_proactive != (revision, text)):
                return
            self._pending_proactive = None
        receiver(text)

    def _emit_proactive(
        self,
        text: str,
        generation: int,
        revision: int,
        service: AIService,
    ) -> None:
        if generation != self._generation or service is not self._service:
            service.discard_proactive_reply(text)
            return
        callback = self._on_proactive
        if callback is None:
            return
        with self._proactive_lock:
            if revision != self._proactive_revision:
                stale = True
            else:
                stale = False
                self._pending_proactive = (revision, text)
        if stale:
            service.discard_proactive_reply(text)
            return
        try:
            callback(text, revision)
        except Exception:
            with self._proactive_lock:
                if self._pending_proactive == (revision, text):
                    self._pending_proactive = None
            service.discard_proactive_reply(text)
            _log.exception("companion proactive callback failed")

    # ── 后台 tick (启用时运行) ──

    def _start_background(self):
        if self._bg_running:
            return
        if not self._service or not self._service.char_id:
            return
        if not cfg.load_player_config().get("background_proactive", True):
            return  # 后台主动关闭，则不启动 tick
        generation = self._generation
        service = self._service
        service.rebind_state(snapshot_state(self._state, self._player))
        self._bg_running = True
        self._bg_ready = threading.Event()
        self._bg_thread = threading.Thread(
            target=self._bg_main, args=(generation, service),
            name="companion-bg", daemon=True,
        )
        self._bg_thread.start()

    def _stop_background(self):
        thread = self._bg_thread
        if thread is None:
            self._bg_running = False
            return
        self._bg_running = False
        loop = self._bg_loop
        task = self._bg_tick_task
        if loop and loop.is_running():
            try:
                if task is not None:
                    loop.call_soon_threadsafe(task.cancel)
                else:
                    loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                _log.debug("companion background loop already stopped")
        thread.join(timeout=3.0)
        if thread.is_alive():
            raise RuntimeError(
                "companion background thread did not stop in time")
        self._bg_thread = None
        self._bg_loop = None
        self._bg_tick_task = None
        self._bg_ready = None

    def _bg_main(self, generation: int, service: AIService):
        self._bg_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._bg_loop)
        try:
            self._bg_tick_task = self._bg_loop.create_task(
                self._tick_loop(generation, service))
            if self._bg_ready:
                self._bg_ready.set()
            self._bg_loop.run_until_complete(self._bg_tick_task)
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.exception("bg loop crashed")
        finally:
            try:
                self._bg_loop.run_until_complete(
                    self._bg_loop.shutdown_asyncgens())
                self._bg_loop.close()
            except RuntimeError:
                _log.debug("companion background loop close failed", exc_info=True)

    async def _tick_loop(self, generation: int, service: AIService):
        try:
            while self._bg_running and generation == self._generation:
                await asyncio.sleep(_TICK_INTERVAL)
                if (
                    not self._bg_running
                    or generation != self._generation
                    or service is not self._service
                ):
                    continue
                try:
                    service.rebind_state(
                        snapshot_state(self._state, self._player))
                    reason = service.tick()
                except Exception:
                    _log.debug("tick failed", exc_info=True)
                    reason = None
                if not reason:
                    continue
                # 触发主动搭话 → 流到字符串 → 通过回调通知 UI
                try:
                    text = ""
                    revision = self.proactive_revision
                    async for chunk in service.proactive_chat(reason):
                        if (
                            generation != self._generation
                            or service is not self._service
                        ):
                            break
                        text += chunk
                    text = text.strip()
                    if text:
                        self._emit_proactive(
                            text, generation, revision, service)
                except Exception:
                    _log.debug("proactive_chat failed", exc_info=True)
        except asyncio.CancelledError:
            raise

    # ── 关停 ──

    def shutdown(self):
        self.clear_session()

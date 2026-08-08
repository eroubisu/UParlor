"""WindowEngine — 引擎控制器

把 WindowRegistry + OverlayStack + 宿主 widget 连成可用的窗口系统。

宿主集成 3 步:
    1. engine = WindowEngine()
    2. engine.attach(host_widget, context_provider)
       - host_widget: 支持 query_one(f"#{id}") 的容器 (通常是 Screen)
       - context_provider: () -> Any, 引擎每次需要 context 时调用
    3. compose 时 yield from engine.compose_all()

之后:
    engine.open("chat-window")              # 打开浮窗 (走 preconditions/bind/show/push/on_open)
    engine.set_primary("lobby-window")      # 切换主窗口 (隐藏旧的, 显示新的)
    engine.close_top()                       # 关闭栈顶浮窗 (或返回 False)
    engine.close_all()                       # 关闭所有浮窗
    engine.active_window()                   # 当前活动窗口 (栈顶浮窗 / 主窗口)
    engine.menu_items("root")                # 某菜单组的 (title, id) 列表
    engine.is_open(id)                       # 是否打开
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Iterator

from .overlay import OverlayStack
from .registry import WindowRegistry, get_registry


def _cancel_staged_presentation(window) -> None:
    cancel = getattr(window, "cancel_staged_presentation", None)
    if cancel is not None:
        cancel()
from .spec import WindowSpec

_LOG = logging.getLogger(__name__)


class WindowEngine:
    """窗口引擎主控制器"""

    def __init__(self, registry: WindowRegistry | None = None):
        self._registry = registry or get_registry()
        self._overlay = OverlayStack()
        self._primary_id: str | None = None
        self._host = None  # 宿主 widget (有 query_one 方法)
        self._context_provider: Callable[[], Any] = lambda: None
        # 全局 on_open/on_close 监听器 (与单窗口 spec hook 互补)
        self._listeners: list[Callable[[str, str], None]] = []
        self._modal = None
        self._presenting: set[str] = set()
        self._pending_primary: dict[str, str | None] = {}
        self._pending_activation: set[str] = set()
        self._pending_replacements: dict[str, tuple[str, ...]] = {}
        self._pending_dismissals: dict[str, tuple[str, ...]] = {}
        self._pending_present_callbacks: dict[str, Callable[[], None]] = {}

    # ── 宿主绑定 ──

    def attach(self, host, context_provider: Callable[[], Any] | None = None) -> None:
        """绑定到宿主 widget。host 需支持 query_one(f"#{id}")"""
        self._host = host
        if context_provider is not None:
            self._context_provider = context_provider

    def add_listener(self, cb: Callable[[str, str], None]) -> None:
        """订阅生命周期事件: cb(event, window_id)
        event ∈ {"open", "close"}"""
        self._listeners.append(cb)

    def _emit(self, event: str, window_id: str) -> None:
        for cb in self._listeners:
            try:
                cb(event, window_id)
            except Exception:
                _LOG.exception(
                    "window lifecycle listener failed: event=%s window=%s",
                    event,
                    window_id,
                )

    # ── compose ──

    def compose_all(self) -> Iterator:
        """生成所有已注册窗口的实例。在 Screen.compose() 中 yield from。"""
        for cls in self._registry.all_classes():
            spec: WindowSpec = cls.spec
            window = cls(id=spec.id)
            if spec.mode == "primary":
                window.add_class("-primary")
            elif spec.mode == "popup":
                window.add_class("-popup")
            set_observer = getattr(window, "set_presentation_observer", None)
            if set_observer is not None:
                set_observer(
                    lambda stage, window_id=spec.id:
                    self._on_presentation_stage(window_id, stage)
                )
            self._set_window_active(window, False)
            yield window

    # ── 窗口查询 ──

    def _query(self, window_id: str):
        if not self._host:
            return None
        try:
            return self._host.query_one(f"#{window_id}")
        except Exception:
            _LOG.exception("registered window query failed: %s", window_id)
            return None

    def is_open(self, window_id: str) -> bool:
        w = self._query(window_id)
        return bool(w and w.has_class("visible"))

    def get_window(self, window_id: str):
        """获取窗口实例 (可能为 None)"""
        return self._query(window_id)

    # ── 打开 ──

    def open(self, window_id: str, **bind_kwargs) -> bool:
        """打开窗口 (mode 由 spec 决定)。

        bind_kwargs: 透传给 spec.bind, 用于偶尔需要的额外参数 (如 dm peer)
        返回是否成功。
        """
        spec = self._registry.spec(window_id)
        if not spec:
            return False
        ctx = self._context_provider()

        for pred in spec.preconditions:
            if not pred(ctx):
                if spec.on_blocked:
                    try:
                        spec.on_blocked(ctx, spec)
                    except Exception:
                        _LOG.exception(
                            "window blocked hook failed: window=%s", spec.id
                        )
                return False

        w = self._query(window_id)
        if w is None:
            return False

        if spec.mode == "primary":
            return self._do_open_primary(spec, w, ctx, bind_kwargs)
        return self._do_open_floating(spec, w, ctx, bind_kwargs)

    def _do_open_floating(self, spec: WindowSpec, w, ctx, bind_kwargs: dict) -> bool:
        already_active = self.active_window() is w and w.has_class("visible")
        try:
            self._invoke_bind(spec, w, ctx, bind_kwargs)
        except Exception:
            _cancel_staged_presentation(w)
            raise
        if already_active:
            self._sync_primitives(w)
            return True
        self._cancel_pending_mode(spec.mode, except_id=spec.id)
        replacements = ()
        if spec.mode == "floating":
            replacements = tuple(
                window_id for window_id in self._overlay
                if window_id != spec.id
                and self._is_visible_floating(window_id)
            )
            self._pending_replacements[spec.id] = replacements
        self._begin_presentation(spec)
        self._pending_activation.add(spec.id)
        try:
            w.show()
        except Exception:
            self._pending_activation.discard(spec.id)
            self._pending_replacements.pop(spec.id, None)
            self._finish_presentation(spec.id)
            raise
        self._sync_primitives(w)
        return True

    def _do_open_primary(self, spec: WindowSpec, w, ctx, bind_kwargs: dict) -> bool:
        previous = self.active_window()
        already_active = previous is w and w.has_class("visible")
        old_id = self._primary_id if self._primary_id != spec.id else None
        old = self._query(old_id) if old_id else None

        # Binding is the only fallible preparation step. Keep the current
        # primary intact until the replacement is ready to commit.
        try:
            self._invoke_bind(spec, w, ctx, bind_kwargs)
        except Exception:
            _cancel_staged_presentation(w)
            raise
        if not already_active:
            self._cancel_pending_mode("primary", except_id=spec.id)
            self._pending_primary[spec.id] = old_id
            self._begin_presentation(spec)
            try:
                w.show()
            except Exception:
                self._pending_primary.pop(spec.id, None)
                self._finish_presentation(spec.id)
                _cancel_staged_presentation(w)
                raise
        self._sync_primitives(w)
        return True

    def set_primary(
        self, window_id: str, *, dismiss_overlays: bool = False,
        on_present: Callable[[], None] | None = None,
        **bind_kwargs,
    ) -> bool:
        """Switch primary and optionally dismiss overlays at presentation."""
        dismissals = tuple(self._overlay) if dismiss_overlays else ()
        if dismissals:
            self._pending_dismissals[window_id] = dismissals
        if on_present is not None:
            self._pending_present_callbacks[window_id] = on_present
        try:
            opened = self.open(window_id, **bind_kwargs)
        except Exception:
            self._pending_dismissals.pop(window_id, None)
            self._pending_present_callbacks.pop(window_id, None)
            raise
        if not opened:
            self._pending_dismissals.pop(window_id, None)
            self._pending_present_callbacks.pop(window_id, None)
            window = self._query(window_id)
            if window is not None:
                _cancel_staged_presentation(window)
        elif window_id not in self._presenting:
            callback = self._pending_present_callbacks.pop(window_id, None)
            if callback is not None:
                callback()
        return opened

    def open_from_popup(
        self, popup_id: str, window_id: str, **bind_kwargs,
    ) -> bool:
        """Keep a popup visible until its selected destination is presented."""
        popup_spec = self._registry.spec(popup_id)
        if popup_spec is None or popup_spec.mode != "popup":
            return False
        if not self.is_open(popup_id):
            return False
        self._pending_dismissals[window_id] = (popup_id,)
        try:
            opened = self.open(window_id, **bind_kwargs)
        except Exception:
            self._pending_dismissals.pop(window_id, None)
            raise
        if not opened:
            self._pending_dismissals.pop(window_id, None)
        return opened

    # ── 关闭 ──

    def close_top(self) -> bool:
        """关闭栈顶可见浮窗。返回是否关闭成功。"""
        ctx = self._context_provider()
        while True:
            previous = self.active_window()
            wid = self._overlay.pop_top()
            if not wid:
                return False
            w = self._query(wid)
            if w is None:
                continue
            if w.has_class("visible"):
                self._pending_replacements.pop(wid, None)
                self._pending_dismissals.pop(wid, None)
                w.hide()
                self._sync_active_window(previous)
                self._sync_primitives(w)
                spec = self._registry.spec(wid)
                if spec:
                    self._invoke_close_hook(wid, w, ctx)
                self._emit("close", wid)
                return True

    def close(self, window_id: str) -> bool:
        """显式关闭指定窗口 (不论是否栈顶)"""
        previous = self.active_window()
        spec = self._registry.spec(window_id)
        if spec and spec.mode == "primary":
            return False
        w = self._query(window_id)
        if w is None or not w.has_class("visible"):
            self._overlay.remove(window_id)
            return False
        self._pending_replacements.pop(window_id, None)
        self._pending_dismissals.pop(window_id, None)
        w.hide()
        self._overlay.remove(window_id)
        self._sync_active_window(previous)
        ctx = self._context_provider()
        if spec:
            self._invoke_close_hook(window_id, w, ctx)
        self._sync_primitives(w)
        self._emit("close", window_id)
        return True

    def close_all(self) -> None:
        """关闭所有浮窗 (不动主窗口)"""
        while self.close_top():
            pass

    # ── 活动窗口 ──

    def active_window(self):
        """返回当前活动窗口实例: 栈顶可见浮窗优先, 否则当前主窗口"""
        for wid in reversed(self._overlay):
            w = self._query(wid)
            if w and w.has_class("visible"):
                return w
        if self._primary_id:
            return self._query(self._primary_id)
        return None

    def active_id(self) -> str | None:
        w = self.active_window()
        return getattr(w, "id", None) if w else None

    def active_focused_panel(self):
        """活动窗口当前聚焦的 Panel (用于宿主的键盘事件分发)"""
        w = self.active_window()
        if w is None:
            return None
        return getattr(w, "focused_panel", None)

    def focus_panel(self, panel_id: str, window_id: str | None = None) -> bool:
        """Focus an addressed panel through the active window lifecycle."""
        window = self.get_window(window_id) if window_id else self.active_window()
        focus = getattr(window, "focus_panel", None)
        if focus is None:
            return False
        focused = bool(focus(panel_id))
        if focused:
            self._sync_primitives(window)
        return focused

    def enter_insert(self, *, sticky: bool = False) -> bool:
        """Ask the focused panel's declared InputSession to enter INSERT."""
        panel = self.active_focused_panel()
        enter = getattr(panel, "enter_insert", None)
        if enter is None:
            return False
        return bool(enter(sticky=sticky))

    def leave_insert(self, *, preserve: bool = True) -> None:
        """Leave INSERT through the focused panel while preserving its draft."""
        panel = self.active_focused_panel()
        leave = getattr(panel, "leave_insert", None)
        if leave is not None:
            leave(preserve=preserve)

    def open_overlay(self, overlay_id: str) -> bool:
        """Activate a composed transient overlay inside the engine stack."""
        widget = self._query(overlay_id)
        if widget is None:
            return False
        previous = self.active_window()
        show = getattr(widget, "show", None)
        if show is None:
            return False
        show()
        self._overlay.push(overlay_id)
        self._sync_active_window(previous)
        self._sync_primitives(widget)
        self._emit("open", overlay_id)
        return True

    def open_modal(self, modal, callback: Callable[[Any], None]) -> bool:
        """Push a Textual modal while keeping activation in engine lifecycle."""
        if self._host is None:
            return False
        app = getattr(self._host, "app", None)
        if app is None:
            return False
        previous = self.active_window()
        self._modal = modal
        modal_id = getattr(modal, "id", None) or type(modal).__name__
        if previous is not None:
            self._set_window_active(previous, False)
            self._sync_primitives(previous)

        def _resolved(result) -> None:
            self._modal = None
            current = self.active_window()
            if current is not None:
                self._set_window_active(current, True)
                self._sync_primitives(current)
            self._emit("close", modal_id)
            callback(result)

        app.push_screen(modal, _resolved)
        self._emit("open", modal_id)
        return True

    def primary_id(self) -> str | None:
        return self._primary_id

    # ── 菜单 ──

    def menu_items(self, group: str = "root") -> list[tuple[str, str]]:
        """Return ``(title, window_id)`` rows for a selectable menu."""
        return [
            (spec.title, spec.id)
            for spec in self._registry.menu_entries(group)
        ]

    # ── 内部 ──

    @staticmethod
    def _set_window_active(window, active: bool) -> None:
        setter = getattr(window, "set_active", None)
        if setter is not None:
            setter(active)

    def _sync_active_window(self, previous) -> None:
        current = self.active_window()
        if previous is current:
            return
        if previous is not None:
            self._set_window_active(previous, False)
            self._sync_primitives(previous)
        if current is not None:
            self._set_window_active(current, True)
            self._sync_primitives(current)

    @staticmethod
    def _sync_primitives(window) -> None:
        sync = getattr(window, "sync_primitives", None)
        if sync is not None:
            sync()

    def _invoke_bind(self, spec: WindowSpec, w, ctx, bind_kwargs: dict) -> None:
        if spec.bind is None:
            return
        if bind_kwargs:
            signature = inspect.signature(spec.bind)
            try:
                signature.bind(w, ctx, **bind_kwargs)
            except TypeError:
                signature.bind(w, ctx)
                spec.bind(w, ctx)
                return
            spec.bind(w, ctx, **bind_kwargs)
        else:
            spec.bind(w, ctx)

    def _invoke_lifecycle(self, hook, w, ctx) -> None:
        if hook is None:
            return
        try:
            hook(w, ctx)
        except Exception:
            _LOG.exception(
                "window lifecycle hook failed: hook=%r window=%s",
                hook,
                getattr(w, "id", "<unknown>"),
            )
            raise

    def _invoke_close_hook(self, window_id: str, w, ctx) -> None:
        spec = self._registry.spec(window_id)
        if spec and spec.on_close:
            self._invoke_lifecycle(spec.on_close, w, ctx)

    def _begin_presentation(self, spec: WindowSpec) -> None:
        self._presenting.add(spec.id)

    def _on_presentation_stage(self, window_id: str, stage: str) -> None:
        if window_id not in self._presenting:
            return
        if stage == "presenting":
            previous = self.active_window()
            spec = self._registry.spec(window_id)
            if spec is not None and spec.mode != "primary":
                self._pending_activation.discard(window_id)
                self._overlay.push(window_id)
            self._commit_primary(window_id)
            self._commit_replacements(window_id)
            self._commit_dismissals(window_id)
            callback = self._pending_present_callbacks.pop(window_id, None)
            if callback is not None:
                callback()
            self._sync_active_window(previous)
            window = self._query(window_id)
            if window is not None:
                self._invoke_lifecycle(
                    spec.on_open if spec is not None else None,
                    window,
                    self._context_provider(),
                )
                self._emit("open", window_id)
        elif stage == "presented":
            self._finish_presentation(window_id)

    def _finish_presentation(self, window_id: str) -> None:
        self._presenting.discard(window_id)

    def _cancel_pending_mode(
        self, mode: str, *, except_id: str | None = None,
    ) -> None:
        """Cancel superseded off-screen presentations in one window mode."""
        pending = (
            tuple(self._pending_primary)
            if mode == "primary"
            else tuple(self._pending_activation)
        )
        for window_id in pending:
            spec = self._registry.spec(window_id)
            if (
                window_id == except_id
                or spec is None
                or spec.mode != mode
            ):
                continue
            window = self._query(window_id)
            if window is not None:
                window.hide()
            self._pending_primary.pop(window_id, None)
            self._pending_activation.discard(window_id)
            self._pending_replacements.pop(window_id, None)
            self._pending_dismissals.pop(window_id, None)
            self._pending_present_callbacks.pop(window_id, None)
            self._finish_presentation(window_id)

    def _is_visible_floating(self, window_id: str) -> bool:
        spec = self._registry.spec(window_id)
        window = self._query(window_id)
        return bool(
            spec
            and spec.mode == "floating"
            and window
            and window.has_class("visible")
        )

    def _commit_primary(self, window_id: str) -> None:
        if window_id not in self._pending_primary:
            return
        old_id = self._pending_primary.pop(window_id)
        old = self._query(old_id) if old_id else None
        if old is not None and old.has_class("visible"):
            old.hide()
            ctx = self._context_provider()
            self._invoke_close_hook(old_id, old, ctx)
            self._emit("close", old_id)
        self._primary_id = window_id

    def _commit_replacements(self, window_id: str) -> None:
        ctx = self._context_provider()
        for replaced_id in self._pending_replacements.pop(window_id, ()):
            replaced = self._query(replaced_id)
            if replaced is None or not replaced.has_class("visible"):
                self._overlay.remove(replaced_id)
                continue
            replaced.hide()
            self._overlay.remove(replaced_id)
            self._invoke_close_hook(replaced_id, replaced, ctx)
            self._emit("close", replaced_id)

    def _commit_dismissals(self, window_id: str) -> None:
        ctx = self._context_provider()
        for dismissed_id in self._pending_dismissals.pop(window_id, ()):
            dismissed = self._query(dismissed_id)
            if dismissed is None or not dismissed.has_class("visible"):
                self._overlay.remove(dismissed_id)
                continue
            dismissed.hide()
            self._overlay.remove(dismissed_id)
            self._invoke_close_hook(dismissed_id, dismissed, ctx)
            self._emit("close", dismissed_id)

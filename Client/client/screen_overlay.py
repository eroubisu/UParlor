"""浮窗栈管理 — overlay push / pop / toggle"""

from __future__ import annotations


class OverlayMixin:
    """浮窗 overlay 栈管理"""

    def _push_overlay(self, wid: str) -> None:
        if wid in self._overlay_stack:
            self._overlay_stack.remove(wid)
        self._overlay_stack.append(wid)

    def _close_overlay(self) -> bool:
        """关闭最顶层 overlay 浮窗，返回是否有浮窗被关闭"""
        while self._overlay_stack:
            wid = self._overlay_stack.pop()
            try:
                w = self.query_one(f"#{wid}")
            except Exception:
                continue
            if w.has_class("visible"):
                w.hide()
                return True
        return False

    def _close_all_overlays(self):
        """关闭所有 overlay 浮窗"""
        while self._close_overlay():
            pass

    def _close_game_select_overlay(self):
        """关闭游戏选择浮窗"""
        try:
            gw = self.query_one("#game-select-window")
            if gw.has_class("visible"):
                gw.remove_class("visible")
                self._overlay_stack = [w for w in self._overlay_stack if w != "game-select-window"]
        except Exception:
            pass

    def _get_active_window(self):
        """获取当前活动的 Window（overlay 浮窗优先，后开的在前）"""
        for wid in reversed(self._overlay_stack):
            try:
                w = self.query_one(f"#{wid}")
                if w.has_class("visible"):
                    return w
            except Exception:
                continue
        if self.mode == "tutorial":
            try:
                return self.query_one("#tutorial-window")
            except Exception:
                return None
        if self.mode == "login":
            try:
                return self.query_one("#login-window")
            except Exception:
                return None
        for wid in ('#game-window', '#waiting-window', '#lobby-window'):
            try:
                w = self.query_one(wid)
                if w.has_class('visible'):
                    return w
            except Exception:
                continue
        return None

    def _get_focused_widget(self):
        for wid in reversed(self._overlay_stack):
            try:
                w = self.query_one(f"#{wid}")
                if w.has_class("visible"):
                    return w.focused_panel
            except Exception:
                continue
        if self.mode == "tutorial":
            try:
                return self.query_one("#tutorial-window").focused_panel
            except Exception:
                return None
        if self.mode == "login":
            return self.get_module('login')
        for wid in ('#game-window', '#waiting-window', '#lobby-window'):
            try:
                w = self.query_one(wid)
                if w.has_class('visible'):
                    return w.focused_panel
            except Exception:
                continue
        return None

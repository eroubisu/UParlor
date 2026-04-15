"""Space 菜单 Mixin — Which-Key 弹窗面板/窗口操作"""

from __future__ import annotations

from ..registry import get_module_names, get_module_labels, get_module_descs
from .layout import PRESETS


class SpaceMenuMixin:
    """GameScreen 的 Space 快捷菜单逻辑"""

    def _open_space_menu(self):
        """构建列表数据并打开 Space 菜单"""
        # 切换面板
        modules = get_module_names(scope='global')
        labels = get_module_labels(scope='global')
        descs = get_module_descs(scope='global')
        mod_items = [
            (labels.get(m, m), descs.get(m, ''), None, str(i + 1))
            for i, m in enumerate(modules)
        ]
        # 调整大小子菜单
        resize_items = [
            ("←", "向左缩小", None, "h"),
            ("→", "向右扩大", None, "l"),
            ("↑", "向上缩小", None, "k"),
            ("↓", "向下扩大", None, "j"),
        ]
        # 预设布局子菜单
        preset_items = [
            (name, "", None, str(i + 1))
            for i, (name, _) in enumerate(PRESETS)
        ]
        # 窗口
        win_items = [
            ("横分", "水平分割当前窗格", None, "|"),
            ("纵分", "垂直分割当前窗格", None, "-"),
            ("关闭", "关闭当前窗格", None, "q"),
            ("全屏", "全屏切换", None, "z"),
            ("交换", "与兄弟窗格交换", None, "x"),
            ("均分", "均分窗格大小", None, "="),
            ("调整", "调整窗格大小", resize_items, "r"),
            ("预设", "切换布局预设", preset_items, "t"),
            ("刷新", "重建所有窗格", None, "f"),
        ]
        # 顶级列表
        items = [
            ("面板", "替换当前窗格内容", mod_items, "b"),
            ("窗口", "分割与关闭窗格", win_items, "w"),
        ]
        self._wk.open(items)

    def _handle_space_enter(self):
        """处理 Space 菜单的 Enter 确认"""
        result = self._wk.enter()
        if result is None:
            return  # 进入了子菜单
        tab_name, idx = result
        if tab_name == "面板":
            modules = get_module_names(scope='global')
            if idx < len(modules):
                self._wk.close()
                self.call_later(self._do_open_module, modules[idx])
        elif tab_name == "窗口":
            self._wk.close()
            if idx == 0:
                self.call_later(self._do_split, 'h')
            elif idx == 1:
                self.call_later(self._do_split, 'v')
            elif idx == 2:
                self.call_later(self._do_close_pane)
            elif idx == 3:
                self.call_later(self._do_zoom)
            elif idx == 4:
                self.call_later(self._do_swap)
            elif idx == 5:
                self._do_equalize()
            elif idx == 8:
                self.call_later(self._do_refresh_panes)
        elif tab_name == "调整":
            self._wk.close()
            delta = 0.3
            if idx == 0:
                self._resize_focused(-delta, 'h')
            elif idx == 1:
                self._resize_focused(delta, 'h')
            elif idx == 2:
                self._resize_focused(-delta, 'v')
            elif idx == 3:
                self._resize_focused(delta, 'v')
        elif tab_name == "预设":
            self._wk.close()
            self.call_later(self._do_load_preset, idx)

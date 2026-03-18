"""Space 菜单 Mixin — Which-Key 弹窗面板/窗口操作"""

from __future__ import annotations

from ..registry import get_module_names, get_module_labels, get_module_descs


class SpaceMenuMixin:
    """GameScreen 的 Space 快捷菜单逻辑"""

    def _open_space_menu(self):
        """构建列表数据并打开 Space 菜单"""
        # 切换面板
        modules = get_module_names(scope='global')
        labels = get_module_labels(scope='global')
        descs = get_module_descs(scope='global')
        mod_items = [(labels.get(m, m), descs.get(m, '')) for m in modules]
        # 窗口
        win_items = [
            ("横分", "水平分割当前窗格"),
            ("纵分", "垂直分割当前窗格"),
            ("关闭", "关闭当前窗格"),
            ("刷新", "重建所有窗格"),
        ]
        # 顶级列表
        items = [
            ("面板", "替换当前窗格内容", mod_items),
            ("窗口", "分割与关闭窗格", win_items),
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
                self.call_later(self._do_refresh_panes)

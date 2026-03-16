"""Space 菜单 Mixin — Which-Key 弹窗面板/游戏/窗口操作"""

from __future__ import annotations

from ..registry import get_module_names, get_module_labels
from .layout import find_module_pane, find_pane


class SpaceMenuMixin:
    """GameScreen 的 Space 快捷菜单逻辑"""

    def _open_space_menu(self):
        """构建列表数据并打开 Space 菜单"""
        # 切换面板
        modules = get_module_names(scope='global')
        labels = get_module_labels(scope='global')
        mod_items = [(labels.get(m, m), "") for m in modules]
        # 游戏
        game_items = self._build_game_tab_items()
        # 窗口
        win_items = [
            ("横分", ""),
            ("纵分", ""),
            ("关闭", "关闭当前窗格"),
        ]
        # 顶级列表：每个分类是带子菜单的项
        items = [
            ("面板", "", mod_items),
            ("游戏", "", game_items),
            ("窗口", "", win_items),
        ]
        self._wk.open(items)

    def _build_game_tab_items(self):
        """构建游戏标签页：按游戏分组，每个游戏是子菜单入口"""
        game_mods = get_module_names(scope='game')
        if not game_mods:
            from ..config import M_DIM, M_END
            return [(f"{M_DIM}暂无游戏{M_END}", "")]
        from ..config import COLOR_ACCENT, COLOR_FG_TERTIARY, M_END
        game_labels = get_module_labels(scope='game')
        items = []
        for m in game_mods:
            label = game_labels.get(m, m)
            opened = find_module_pane(self._layout_tree, m) is not None
            if opened:
                mark = f"[{COLOR_ACCENT}]●{M_END}"
            else:
                mark = f"[{COLOR_FG_TERTIARY}]○{M_END}"
            items.append((f"{mark} {label}", ""))
        if len(game_mods) > 1:
            items.append(("全选/取消", ""))
        return items

    def _refresh_game_tab(self):
        """刷新游戏分类的 ●/○ 状态"""
        items = self._build_game_tab_items()
        self._wk.refresh_category_items("游戏", items)

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
        elif tab_name == "游戏":
            game_mods = get_module_names(scope='game')
            if game_mods:
                if idx < len(game_mods):
                    self._toggle_game_module(game_mods[idx])
                    self._refresh_game_tab()
                else:
                    self._toggle_all_game_modules(game_mods)
                    self._refresh_game_tab()
        elif tab_name == "窗口":
            self._wk.close()
            if idx == 0:
                self.call_later(self._do_split, 'h')
            elif idx == 1:
                self.call_later(self._do_split, 'v')
            elif idx == 2:
                self.call_later(self._do_close_pane)

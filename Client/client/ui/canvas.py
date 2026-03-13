"""
画布渲染系统 — 根据布局树动态构建 Textual Widget 树

核心设计：
  Widget 是无状态视图，状态由 state.py 管理。
  所有布局变更（split/close）通过 rebuild() 销毁并重建全部 Widget，
  随后由 GameScreen._restore_all_modules() 从 State 恢复内容。
  resize 仅更新 CSS 权重，不触发 rebuild。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static, RichLog
from textual.containers import Horizontal, Vertical

from .layout import (
    LayoutNode, PaneNode, SplitNode,
    all_panes, find_pane, find_module_pane,
)
from ..registry import get_module_info, get_module_labels


# ── 空窗格占位 ──

class EmptyPane(Widget):
    """空窗格显示提示"""

    def compose(self) -> ComposeResult:
        yield Static("Space 打开菜单", classes="empty-hint")


# ── 窗格包装器 ──

class PaneWrapper(Widget):
    """包装一个模块 Widget 的窗格容器"""

    def __init__(self, pane_id: str, module: str | None = None,
                 module_widget: Widget | None = None, **kw):
        super().__init__(id=pane_id, **kw)
        self.pane_id = pane_id
        self.module_name = module
        self._module_widget = module_widget

    def compose(self) -> ComposeResult:
        if self._module_widget:
            yield self._module_widget
        else:
            yield EmptyPane()

    def on_mount(self) -> None:
        labels = get_module_labels()
        label = labels.get(self.module_name, '') if self.module_name else ''
        self.border_title = label

    @property
    def module_widget(self) -> Widget | None:
        return self._module_widget

    async def set_module(self, module_name: str | None,
                         module_widget: Widget | None = None):
        """替换当前模块"""
        self.module_name = module_name
        await self.remove_children()
        if module_widget:
            self._module_widget = module_widget
            await self.mount(module_widget)
        else:
            self._module_widget = None
            await self.mount(EmptyPane())
        label = get_module_labels().get(module_name, '') if module_name else ''
        self.border_title = label


# ── 画布 ──

class Canvas(Widget):
    """
    动态画布：布局树 → Textual Widget 树

    所有布局变更（split/close）统一走 rebuild() —— 销毁全部 Widget 后重建。
    Widget 内容不在此保留，由调用方通过 State 恢复。
    resize 不触发 rebuild，仅 sync_weights 更新 CSS。
    """

    def __init__(self, layout_tree: LayoutNode, **kw):
        super().__init__(**kw)
        self._layout_tree = layout_tree

    @property
    def layout_tree(self) -> LayoutNode:
        return self._layout_tree

    def compose(self) -> ComposeResult:
        yield from self._build_node(self._layout_tree)

    def _build_node(self, node: LayoutNode, weight: float = 1.0, parent_dir: str | None = None):
        if isinstance(node, PaneNode):
            widget = None
            info = get_module_info(node.module) if node.module else None
            if info:
                widget = info['class']()
            pw = PaneWrapper(node.pane_id, node.module, module_widget=widget, classes="pane-wrapper")
            if parent_dir == 'h':
                pw.styles.width = f"{weight:g}fr"
            elif parent_dir == 'v':
                pw.styles.height = f"{weight:g}fr"
            yield pw
        elif isinstance(node, SplitNode):
            container_cls = Horizontal if node.direction == 'h' else Vertical
            children = []
            for child, w in zip(node.children, node.weights):
                children.extend(self._build_node(child, w, node.direction))
            container = container_cls(*children, classes=f"split-{'h' if node.direction == 'h' else 'v'}")
            if parent_dir == 'h':
                container.styles.width = f"{weight:g}fr"
            elif parent_dir == 'v':
                container.styles.height = f"{weight:g}fr"
            yield container

    async def rebuild(self, new_tree: LayoutNode):
        """
        销毁全部 DOM 子树，根据新布局树重建。

        调用方（GameScreen）必须在 rebuild 之后调用 _restore_all_modules()
        将 State 层数据重新推送到新创建的 Widget 中。
        """
        self._layout_tree = new_tree
        await self.remove_children()
        children = list(self._build_node(new_tree))
        await self.mount_all(children)

    def sync_weights(self, tree: LayoutNode):
        """同步布局树权重到 DOM（仅更新 CSS，不增删节点）"""
        self._layout_tree = tree
        if isinstance(tree, PaneNode):
            return
        for child in self.children:
            if isinstance(child, (Horizontal, Vertical)):
                self._sync_node(tree, child)
                child.refresh(layout=True)
                return

    def _sync_node(self, node: SplitNode, container: Widget):
        prop = 'width' if node.direction == 'h' else 'height'
        for child_node, weight, dom_child in zip(node.children, node.weights, container.children):
            setattr(dom_child.styles, prop, f"{weight:g}fr")
            if isinstance(child_node, SplitNode):
                self._sync_node(child_node, dom_child)

    # ── 查询 ──

    def get_pane(self, pane_id: str) -> PaneWrapper | None:
        try:
            return self.query_one(f"#{pane_id}", PaneWrapper)
        except Exception:
            return None

    def get_module_widget(self, module_name: str) -> Widget | None:
        """查找当前画布中已挂载的模块 Widget 实例"""
        try:
            for pw in self.query(PaneWrapper):
                if pw.module_name == module_name and pw._module_widget:
                    return pw._module_widget
        except Exception:
            pass
        return None

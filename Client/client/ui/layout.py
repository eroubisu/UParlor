"""
布局树引擎 — NVim 风格动态窗口拆分管理
"""

from __future__ import annotations
from dataclasses import dataclass, field

from ..registry import (
    resolve_compat_name, is_known_module,
)


# ── 布局树节点 ──

@dataclass
class PaneNode:
    """叶子节点：一个窗格"""
    module: str | None  # None = 空窗格
    pane_id: str

@dataclass
class SplitNode:
    """拆分节点：水平(h)或垂直(v)容器"""
    direction: str  # 'h' = 水平并排, 'v' = 垂直堆叠
    children: list  # list[PaneNode | SplitNode]
    weights: list[float] = field(default_factory=list)

    def __post_init__(self):
        if not self.weights or len(self.weights) != len(self.children):
            self.weights = [1.0] * len(self.children)


LayoutNode = PaneNode | SplitNode


def get_default_layout() -> LayoutNode:
    """默认布局：登录面板"""
    return PaneNode('login', 'pane-0')


def get_game_layout() -> LayoutNode:
    """游戏布局：左游戏面板 右聊天+记录"""
    return SplitNode('h', [
        PaneNode('game_board', 'pane-0'),
        SplitNode('v', [
            PaneNode('chat', 'pane-1'),
            PaneNode('cmd', 'pane-2'),
        ], [1.0, 1.0]),
    ], [1.0, 1.0])


# ── 序列化 / 反序列化 ──

def serialize(node: LayoutNode) -> dict:
    if isinstance(node, PaneNode):
        return {'type': 'pane', 'module': node.module, 'id': node.pane_id}
    return {
        'type': 'hsplit' if node.direction == 'h' else 'vsplit',
        'children': [serialize(c) for c in node.children],
        'weights': list(node.weights),
    }

def deserialize(data: dict) -> LayoutNode | None:
    if not isinstance(data, dict):
        return None
    t = data.get('type')
    if t == 'pane':
        mod = data.get('module')
        if mod is not None:
            mod = resolve_compat_name(mod)
            if not is_known_module(mod):
                mod = None
        pid = data.get('id', 'pane-0')
        return PaneNode(mod, str(pid))
    if t in ('hsplit', 'vsplit'):
        children_data = data.get('children', [])
        if not isinstance(children_data, list) or len(children_data) < 2:
            return None
        children = []
        for c in children_data:
            child = deserialize(c)
            if child is None:
                return None
            children.append(child)
        weights_data = data.get('weights', [])
        if not isinstance(weights_data, list) or len(weights_data) != len(children):
            weights_data = [1.0] * len(children)
        else:
            weights_data = [float(w) if isinstance(w, (int, float)) else 1.0 for w in weights_data]
        node = SplitNode('h' if t == 'hsplit' else 'v', children, weights_data)
        return _flatten_tree(node)
    return None


# ── 树遍历 ──

def all_panes(node: LayoutNode) -> list[PaneNode]:
    """按深度优先收集所有叶子窗格"""
    if isinstance(node, PaneNode):
        return [node]
    result = []
    for c in node.children:
        result.extend(all_panes(c))
    return result


def find_pane(node: LayoutNode, pane_id: str) -> PaneNode | None:
    if isinstance(node, PaneNode):
        return node if node.pane_id == pane_id else None
    for c in node.children:
        found = find_pane(c, pane_id)
        if found:
            return found
    return None


def find_module_pane(node: LayoutNode, module: str) -> PaneNode | None:
    """查找包含指定模块的窗格"""
    if isinstance(node, PaneNode):
        return node if node.module == module else None
    for c in node.children:
        found = find_module_pane(c, module)
        if found:
            return found
    return None


def next_pane_id(node: LayoutNode) -> str:
    panes = all_panes(node)
    max_id = -1
    for p in panes:
        try:
            num = int(p.pane_id.split('-')[1])
            max_id = max(max_id, num)
        except (IndexError, ValueError):
            pass
    return f"pane-{max_id + 1}"


# ── 树操作 ──

def _find_parent(root: LayoutNode, pane_id: str) -> tuple[SplitNode | None, int]:
    """返回 (父节点, 子节点索引)"""
    if isinstance(root, PaneNode):
        return None, -1
    for i, c in enumerate(root.children):
        if isinstance(c, PaneNode) and c.pane_id == pane_id:
            return root, i
        if isinstance(c, SplitNode):
            parent, idx = _find_parent(c, pane_id)
            if parent is not None:
                return parent, idx
    return None, -1


def _flatten_tree(node: LayoutNode) -> LayoutNode:
    """扁平化同方向嵌套的 SplitNode，消除不等宽问题"""
    if isinstance(node, PaneNode):
        return node
    flat_children = [_flatten_tree(c) for c in node.children]
    flat_weights = list(node.weights)
    new_children = []
    new_weights = []
    for child, w in zip(flat_children, flat_weights):
        if isinstance(child, SplitNode) and child.direction == node.direction:
            for gc, gw in zip(child.children, child.weights):
                new_children.append(gc)
                new_weights.append(w * gw)
        else:
            new_children.append(child)
            new_weights.append(w)
    n = len(new_weights)
    total = sum(new_weights) if new_weights else 1
    new_weights = [w * n / total for w in new_weights]
    return SplitNode(node.direction, new_children, new_weights)


def split_pane(root: LayoutNode, pane_id: str, direction: str) -> LayoutNode:
    """将指定窗格拆分，同方向扁平化插入父节点，所有兄弟等权重"""
    target = find_pane(root, pane_id)
    if not target:
        return root

    new_id = next_pane_id(root)
    new_pane = PaneNode(None, new_id)

    if isinstance(root, PaneNode) and root.pane_id == pane_id:
        return SplitNode(direction, [root, new_pane], [1.0, 1.0])

    parent, idx = _find_parent(root, pane_id)
    if parent is None:
        return root

    if parent.direction == direction:
        parent.children.insert(idx + 1, new_pane)
        parent.weights = [1.0] * len(parent.children)
    else:
        original = parent.children[idx]
        new_split = SplitNode(direction, [original, new_pane], [1.0, 1.0])
        parent.children[idx] = new_split
    return _flatten_tree(root)


def close_pane(root: LayoutNode, pane_id: str) -> LayoutNode | None:
    """关闭指定窗格，返回新的根节点。如果只剩一个窗格则返回 None"""
    if isinstance(root, PaneNode):
        if root.pane_id == pane_id:
            return None
        return root

    parent, idx = _find_parent(root, pane_id)
    if parent is None:
        return root

    parent.children.pop(idx)
    parent.weights = [1.0] * len(parent.children)

    if len(parent.children) == 1:
        sole_child = parent.children[0]
        if parent is root:
            return _flatten_tree(sole_child) if isinstance(sole_child, SplitNode) else sole_child
        _replace_node(root, parent, sole_child)
    return _flatten_tree(root)


def _replace_node(root: SplitNode, target: SplitNode, replacement: LayoutNode):
    """在树中用 replacement 替换 target"""
    for i, c in enumerate(root.children):
        if c is target:
            root.children[i] = replacement
            return
        if isinstance(c, SplitNode):
            _replace_node(c, target, replacement)


# ── 导航 ──

def _path_to_pane(root: LayoutNode, pane_id: str) -> list[tuple[SplitNode, int]] | None:
    """返回从 root 到 pane_id 的路径"""
    if isinstance(root, PaneNode):
        return [] if root.pane_id == pane_id else None
    for i, c in enumerate(root.children):
        sub = _path_to_pane(c, pane_id)
        if sub is not None:
            return [(root, i)] + sub
    return None


def _compute_pane_rects(root: LayoutNode) -> dict[str, tuple[float, float, float, float]]:
    """计算每个窗格的归一化矩形 {pane_id: (x, y, w, h)}"""
    result: dict[str, tuple[float, float, float, float]] = {}
    _layout_rects(root, 0.0, 0.0, 1.0, 1.0, result)
    return result


def _layout_rects(node: LayoutNode, x: float, y: float, w: float, h: float,
                  out: dict[str, tuple[float, float, float, float]]):
    if isinstance(node, PaneNode):
        out[node.pane_id] = (x, y, w, h)
        return
    total_weight = sum(node.weights) or 1.0
    offset = 0.0
    for child, weight in zip(node.children, node.weights):
        ratio = weight / total_weight
        if node.direction == 'h':
            cw = w * ratio
            _layout_rects(child, x + offset, y, cw, h, out)
            offset += cw
        else:
            ch = h * ratio
            _layout_rects(child, x, y + offset, w, ch, out)
            offset += ch


def _overlap_len(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def navigate(root: LayoutNode, current_id: str, direction: str) -> str:
    """空间导航: h=左, l=右, j=下, k=上

    基于归一化坐标，找到目标方向上邻接且重叠最多的窗格。
    """
    rects = _compute_pane_rects(root)
    if current_id not in rects:
        panes = all_panes(root)
        return panes[0].pane_id if panes else current_id

    cx, cy, cw, ch = rects[current_id]
    eps = 1e-6
    best_id = current_id
    best_dist = float('inf')
    best_overlap = -1.0

    for pid, (px, py, pw, ph) in rects.items():
        if pid == current_id:
            continue
        if direction == 'l':       # 右
            dist = px - (cx + cw)
            overlap = _overlap_len(cy, cy + ch, py, py + ph)
        elif direction == 'h':     # 左
            dist = cx - (px + pw)
            overlap = _overlap_len(cy, cy + ch, py, py + ph)
        elif direction == 'j':     # 下
            dist = py - (cy + ch)
            overlap = _overlap_len(cx, cx + cw, px, px + pw)
        elif direction == 'k':     # 上
            dist = cy - (py + ph)
            overlap = _overlap_len(cx, cx + cw, px, px + pw)
        else:
            continue
        if dist < -eps or overlap <= eps:
            continue
        if dist < best_dist - eps or (abs(dist - best_dist) < eps and overlap > best_overlap):
            best_dist = dist
            best_overlap = overlap
            best_id = pid

    return best_id


def resize_pane(root: LayoutNode, pane_id: str, delta: float, direction: str = 'h') -> bool:
    """调整窗格权重，然后归一化使总权重 = 子节点数。返回是否成功。"""
    path = _path_to_pane(root, pane_id)
    if not path:
        return False
    min_weight = 0.2
    for i in range(len(path) - 1, -1, -1):
        parent, child_idx = path[i]
        if parent.direction != direction:
            continue
        new_weight = parent.weights[child_idx] + delta
        if new_weight < min_weight:
            return False
        parent.weights[child_idx] = new_weight
        total = sum(parent.weights)
        n = len(parent.weights)
        parent.weights = [w * n / total for w in parent.weights]
        return True
    return False

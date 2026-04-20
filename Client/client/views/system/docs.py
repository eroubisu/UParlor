"""说明文档 — 左侧目录 + 右侧详情"""

from __future__ import annotations

from textual.app import ComposeResult

from ...widgets.panel import Panel
from ...widgets.window import Window
from ...config import (
    M_DIM, M_BOLD, M_CMD, M_END,
    COLOR_HINT_TAB_DIM,
)

# ── 文档主题 ──

_TOPICS = [
    ('nav',     '方向与导航'),
    ('confirm', '确认与返回'),
    ('menu',    '快捷菜单'),
    ('input',   '输入模式'),
    ('focus',   '面板切换'),
]


def _build_detail(key: str, sep: str) -> str:
    """生成指定主题的详情文档"""
    match key:
        case 'nav':
            return (
                f"{M_BOLD}方向与导航{M_END}\n"
                f"{sep}\n"
                "\n"
                f"{M_DIM}本客户端支持三组等效方向键{M_END}\n"
                f"{M_DIM}可随时混用，效果完全相同{M_END}\n"
                "\n"
                f"  方向键  {M_CMD}←  ↓  ↑  →{M_END}\n"
                f"  游戏键  {M_CMD}A  S  W  D{M_END}\n"
                f"  Vim    {M_CMD}h  j  k  l{M_END}\n"
                "\n"
                f"{sep}\n"
                f"{M_DIM}上下: 移动光标 / 滚动内容{M_END}\n"
                f"{M_DIM}左右: 切换标签页{M_END}"
            )
        case 'confirm':
            return (
                f"{M_BOLD}确认与返回{M_END}\n"
                f"{sep}\n"
                "\n"
                f"  {M_CMD}Enter{M_END}  确认 / 发送\n"
                f"  {M_CMD}Z{M_END}      等效确认键\n"
                "\n"
                f"{sep}\n"
                "\n"
                f"  {M_CMD}Esc{M_END}    返回 / 关闭\n"
                f"  {M_CMD}X{M_END}      等效返回键\n"
                f"  {M_CMD}Q{M_END}      等效返回键"
            )
        case 'menu':
            return (
                f"{M_BOLD}快捷菜单{M_END}\n"
                f"{sep}\n"
                "\n"
                f"  {M_CMD}Space{M_END}  打开快捷菜单\n"
                f"  {M_CMD}C{M_END}      等效菜单键\n"
                "\n"
                f"{sep}\n"
                f"{M_DIM}菜单中按字母键快速打开对应功能：{M_END}\n"
                "\n"
                f"  {M_CMD}c{M_END}  聊天        {M_CMD}o{M_END}  在线\n"
                f"  {M_CMD}n{M_END}  通知        {M_CMD}g{M_END}  游戏\n"
                f"  {M_CMD}s{M_END}  设置"
            )
        case 'input':
            return (
                f"{M_BOLD}输入模式{M_END}\n"
                f"{sep}\n"
                "\n"
                f"  {M_CMD}i{M_END}  进入输入模式\n"
                f"  {M_CMD}I{M_END}  粘滞输入模式\n"
                f"     {M_DIM}(发送后保持打开){M_END}\n"
                "\n"
                f"{sep}\n"
                f"{M_DIM}输入模式中：{M_END}\n"
                "\n"
                f"  直接打字输入内容\n"
                f"  {M_CMD}Enter{M_END}  发送\n"
                f"  {M_CMD}Esc{M_END}    退出输入模式"
            )
        case 'focus':
            return (
                f"{M_BOLD}面板切换{M_END}\n"
                f"{sep}\n"
                "\n"
                f"{M_DIM}大厅有多个面板，用以下按键切换聚焦：{M_END}\n"
                "\n"
                f"  {M_CMD}H/J/K/L{M_END}           Vim 大写\n"
                f"  {M_CMD}Shift+←↓↑→{M_END}     Shift+方向键\n"
                f"  {M_CMD}W/A/S/D{M_END}           大写 WASD\n"
                "\n"
                f"{M_DIM}小写 = 移动光标，大写 = 切换面板{M_END}"
            )
        case _:
            return ''


class DocsListPanel(Panel):
    """文档目录面板（左侧）"""

    icon_align = True
    hide_scrollbar = True
    _labels = [name for _, name in _TOPICS]

    def on_mount(self) -> None:
        super().on_mount()
        self._redraw()
        self._notify_detail()

    def nav(self, action: str) -> None:
        if action in ('up', 'down') and self._move_cursor(
            -1 if action == 'up' else 1, len(_TOPICS)
        ):
            self._redraw()
            self._notify_detail()

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._redraw()
        self._notify_detail()

    def _redraw(self) -> None:
        self.update(self._render_cursor_items(self._labels))

    def _notify_detail(self) -> None:
        """通知右侧详情面板更新"""
        key = _TOPICS[self._cursor][0]
        try:
            parent = self.parent
            if parent:
                detail = parent.query_one("#docs-detail", DocsDetailPanel)
                detail.show_topic(key)
        except Exception:
            pass


class DocsDetailPanel(Panel):
    """文档详情面板（右侧）"""

    hide_scrollbar = False

    def show_topic(self, key: str) -> None:
        sep = self._separator_line(COLOR_HINT_TAB_DIM)
        text = _build_detail(key, sep)
        self.update(text)


class DocsWindow(Window):
    """说明文档浮窗 — 左侧目录 + 右侧详情"""

    DEFAULT_CSS = """
    DocsWindow {
        layer: floating;
        width: 58;
        height: 60%;
    }
    DocsWindow > #docs-list {
        width: 16;
        height: 1fr;
    }
    DocsWindow > #docs-detail {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["docs-list", "docs-detail"]]
    primary_panel = "docs-list"

    def compose(self) -> ComposeResult:
        yield DocsListPanel(id="docs-list")
        yield DocsDetailPanel(id="docs-detail")

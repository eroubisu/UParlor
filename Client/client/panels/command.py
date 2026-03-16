"""CommandPanel + CommandHintBar — 指令面板"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static, RichLog
from textual.widget import Widget

from ..config import COLOR_HINT_TAB_ACTIVE, MAX_LINES_CMD
from ..widgets import TabMenuBase
from ..widgets.input_bar import InputTextArea
from ..state import ModuleStateManager


class CommandHintBar(TabMenuBase):
    """指令输入框：标签页导航 + 指令选择 + 补全 + 输入提示

    继承 TabMenuBase，items 为 CommandInfo 对象。
    额外支持补全模式（completion）。
    """

    _tabs_widget_id = "hint-tabs"
    _content_widget_id = "hint-content"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.border_title = "指令菜单"
        self._mode: str = 'normal'
        self._completion_matches: list = []
        self._prompt_id = "cmd-prompt"

    def compose(self) -> ComposeResult:
        yield Static("", id="hint-tabs", classes="hint-tabs")
        yield Static("", id="hint-content", classes="hint-content")
        yield InputTextArea(
            id="cmd-prompt",
            classes="input-bar-prompt",
            submit_on_enter=True,
            passthrough_chars={"H", "J", "K", "L"},
        )

    # ── TabMenuBase 钩子 ──

    def _item_name(self, item) -> str:
        if self._nav_stack:
            return item.label or item.command
        return item.command

    def _item_desc(self, item) -> str:
        return item.description or ""

    def _item_sub(self, item) -> list | None:
        return item.sub

    def _make_sub_tab(self, item) -> tuple[str, list]:
        return (item.label or item.command, item.sub)

    # ── 补全模式覆盖 ──

    def _current_items(self) -> list:
        if self._mode == 'completion':
            return self._completion_matches
        return super()._current_items()

    def _push_stack(self):
        self._nav_stack.append({
            'tabs': self._tabs,
            'active_tab': self._active_tab,
            'selected_idx': self._selected_idx,
            'scroll_offset': self._scroll_offset,
            'mode': self._mode,
            'completion_matches': self._completion_matches,
        })
        # 钻入子菜单后切回 normal 模式，否则 _current_items 仍返回旧补全列表
        self._mode = 'normal'
        self._completion_matches = []

    def _on_restore_stack(self, state: dict):
        self._mode = state.get('mode', 'normal')
        self._completion_matches = state.get('completion_matches', [])

    def _refresh_display(self):
        if not self._tabs and self._mode != 'completion':
            self._update_widgets("", "")
            return
        if self._mode == 'completion':
            tab_text = f"  [bold {COLOR_HINT_TAB_ACTIVE}]补全[/]"
            items = self._current_items()
            if items:
                content = self._render_items()
            else:
                from ..config import COLOR_HINT_TAB_DIM
                content = f"[{COLOR_HINT_TAB_DIM}]  暂无匹配指令[/]"
            self._update_widgets(tab_text, content)
            return
        super()._refresh_display()

    # ── 导航覆盖（阻止补全模式下切标签） ──

    def nav_left(self):
        if self._mode != 'normal':
            return
        super().nav_left()

    def nav_right(self):
        if self._mode != 'normal':
            return
        super().nav_right()

    # ── back 覆盖（额外处理补全退出） ──

    def back(self) -> bool:
        if self._nav_stack:
            return super().back()
        if self._mode == 'completion':
            self._mode = 'normal'
            self._selected_idx = 0
            self._scroll_offset = 0
            self._completion_matches = []
            self._refresh_display()
            return True
        return False

    def reset_to_root(self):
        self._mode = 'normal'
        self._completion_matches = []
        super().reset_to_root()

    # ── 补全 ──

    def show_completion(self, matches: list):
        self._mode = 'completion'
        self._completion_matches = matches
        self._selected_idx = 0
        self._scroll_offset = 0
        self._refresh_display()

    def exit_completion(self):
        if self._mode == 'completion':
            self._mode = 'normal'
            self._selected_idx = 0
            self._scroll_offset = 0
            self._completion_matches = []
            self._refresh_display()

    # ── 数据更新（覆盖基类以重置补全状态） ──

    def update_tabs(self, tabs: list[tuple[str, list]]):
        self._mode = 'normal'
        self._completion_matches = []
        super().update_tabs(tabs)

    # ── 输入提示代理 ──

    def show_prompt(self, text: str = ""):
        try:
            ta = self.query_one(f"#{self._prompt_id}", InputTextArea)
            ta.text = text
            ta.move_cursor(ta.document.end)
        except Exception:
            pass

    def update_prompt(self, text: str):
        try:
            ta = self.query_one(f"#{self._prompt_id}", InputTextArea)
            ta.text = text
            ta.move_cursor(ta.document.end)
        except Exception:
            pass

    def hide_prompt(self):
        try:
            self.query_one(f"#{self._prompt_id}", InputTextArea).text = ""
        except Exception:
            pass

    def focus_input(self):
        try:
            self.query_one(f"#{self._prompt_id}", InputTextArea).focus()
        except Exception:
            pass


class CommandPanel(Widget):
    """指令面板：纯终端输出 + 指令提示栏"""

    def compose(self) -> ComposeResult:
        yield RichLog(id="cmd-log", wrap=True, highlight=True, markup=True, max_lines=MAX_LINES_CMD)
        yield CommandHintBar(id="cmd-hint-bar")

    def _bar(self) -> CommandHintBar | None:
        try:
            return self.query_one("#cmd-hint-bar", CommandHintBar)
        except Exception:
            return None

    # ── 提示栏代理 ──

    def show_prompt(self, text: str = ""):
        bar = self._bar()
        if bar:
            bar.show_prompt(text)

    def update_prompt(self, text: str):
        bar = self._bar()
        if bar:
            bar.update_prompt(text)

    def hide_prompt(self):
        bar = self._bar()
        if bar:
            bar.hide_prompt()

    def focus_input(self):
        bar = self._bar()
        if bar:
            bar.focus_input()

    # ── 消息 ──

    def echo_command(self, text: str) -> str:
        """p10k 风格回显用户输入的指令，返回格式化后的文本"""
        from ..config import COLOR_HINT_TAB_ACTIVE, COLOR_FG_SECONDARY
        prompt = f"[{COLOR_HINT_TAB_ACTIVE}]>[/] [{COLOR_FG_SECONDARY}]{text}[/]"
        return prompt

    def add_message(self, text: str, update_last: bool = False):
        log: RichLog = self.query_one("#cmd-log", RichLog)
        log.write(text)

    def clear(self):
        log: RichLog = self.query_one("#cmd-log", RichLog)
        log.clear()

    # ── 指令菜单 ──

    def update_hint_tabs(self, tabs: list[tuple[str, list]]):
        bar = self._bar()
        if bar:
            bar.update_tabs(tabs)

    def show_hint_bar(self):
        bar = self._bar()
        if bar:
            bar.reset_to_root()
            bar._refresh_display()
            bar.add_class("visible")
        try:
            self.query_one("#cmd-log", RichLog).scroll_end(animate=False)
        except Exception:
            pass

    def hide_hint_bar(self):
        bar = self._bar()
        if bar:
            bar.remove_class("visible")
            bar.reset_to_root()

    def show_completion(self, matches: list):
        bar = self._bar()
        if bar:
            bar.show_completion(matches)

    def exit_completion(self):
        bar = self._bar()
        if bar:
            bar.exit_completion()

    def hint_enter(self):
        bar = self._bar()
        return bar.enter() if bar else None

    def hint_back(self):
        bar = self._bar()
        if bar:
            bar.back()

    def hint_nav(self, direction: str):
        bar = self._bar()
        if bar:
            getattr(bar, f'nav_{direction}')()

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        try:
            log: RichLog = self.query_one("#cmd-log", RichLog)
        except Exception:
            return
        if event == 'add_line':
            text, kw = args
            log.write(text)
        elif event == 'clear':
            log.clear()

    def restore(self, state: ModuleStateManager):
        st = state.cmd
        st.set_listener(self._on_state_event)
        log: RichLog = self.query_one("#cmd-log", RichLog)
        for line in st.lines:
            log.write(line)
        from ..protocol.commands import get_command_tabs
        tabs = get_command_tabs()
        if tabs:
            self.update_hint_tabs(tabs)

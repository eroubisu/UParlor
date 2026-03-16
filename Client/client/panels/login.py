"""LoginPanel — 登录面板"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static
from textual.widget import Widget

from ..widgets.input_bar import InputBar, InputTextArea
from ..widgets.prompt import InputBarMixin
from ..state import ModuleStateManager

_WELCOME_DOC = """\
[bold]欢迎来到 UParlor[/bold]

────────────────────────────────────

[dim]推荐字体[/dim]
  更纱黑体（SarasaTermSC）
  等宽变体以获得最佳显示效果

[dim]操作指南[/dim]
  [bold]i[/bold]            打开输入窗口
  [bold]Backspace[/bold]    返回上一级
  [bold]Esc / Ctrl+\[[/bold] 退出输入 / 关闭浮窗
  [bold]Enter[/bold]        确定
  [bold]Tab[/bold]          补全指令
  [bold]Space[/bold]        打开浮窗菜单
  [bold]h j k l[/bold]      窗口内移动
  [bold]H J K L[/bold]      窗口间移动

[dim]注意左下角 normal / insert 状态显示[/dim]

────────────────────────────────────

按 [bold]i[/bold] 进入 insert 模式，输入账号密码\
"""


class LoginPanel(InputBarMixin, Widget):
    """登录面板：欢迎文档 + 登录提示"""

    _input_bar_id = "login-input-bar"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="login-doc"):
            yield Static(_WELCOME_DOC, markup=True)
        yield Static("", id="login-prompt-text", markup=True)
        yield InputBar(prompt_id="login-prompt", id="login-input-bar")

    def add_message(self, text: str):
        try:
            self.query_one("#login-prompt-text", Static).update(text)
        except Exception:
            pass

    def restore(self, state: ModuleStateManager):
        pass

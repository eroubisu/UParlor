"""记录面板 — 只读日志，显示服务端推送的消息"""

from __future__ import annotations

from ...widgets.panel import Panel


class LogPanel(Panel):
    """只读日志面板，显示系统消息和指令反馈"""

    title = "记录"
    hide_scrollbar = True

    def _on_state(self, event: str, *args):
        match event:
            case 'add_line':
                text, kw = args
                if kw.get('update_last'):
                    self.replace_last(text)
                else:
                    self.append(text)
            case 'clear':
                self.update("")

    def bind_state(self, st) -> None:
        st.cmd.add_listener(self._on_state)
        # 恢复已有内容
        if st.cmd.lines:
            self.update("\n".join(st.cmd.lines))

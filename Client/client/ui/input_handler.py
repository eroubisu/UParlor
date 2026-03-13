"""InputMixin — 输入提交、指令补全、频道切换"""

from __future__ import annotations

from .panels import ChatPanel, CommandPanel


class InputMixin:
    """输入处理 Mixin — 提供指令/聊天提交与 hint-bar 交互。"""

    # ── 输入提交 ──

    def _submit_input(self):
        text = self._input_buffer.strip()
        self._input_buffer = ""
        self._hide_panel_prompt()
        self._hide_input_bar()
        self.vim.enter_normal()
        self._update_mode_indicator()

        if not text and self._input_target != 'login':
            return

        if self._input_target == 'login':
            if text:
                self._send_command(text)
        elif self._input_target == "chat":
            chat = self._get_module('chat')
            ch = chat.current_channel if isinstance(chat, ChatPanel) else 1
            self._send_chat(text, ch)
        else:
            if not text.startswith("/"):
                text = "/" + text
            # 回显指令
            cmd_panel = self._get_module('cmd')
            if isinstance(cmd_panel, CommandPanel):
                echo = cmd_panel.echo_command(text)
                self.state.cmd.add_line(echo)
            self._send_command(text)
        if not self.logged_in:
            self._enter_insert()

    # ── 指令发送 ──

    def _send_command(self, text: str):
        self.app.send_command(text)

    def _send_chat(self, text: str, channel: int):
        self.app.send_chat(text, channel)

    def _cycle_channel(self):
        chat = self._get_module('chat')
        if not isinstance(chat, ChatPanel):
            return
        ch = chat.current_channel
        new_ch = 2 if ch == 1 else 1
        self.state.chat.switch_channel(new_ch)
        chat.switch_channel(new_ch)
        self.app.switch_channel(new_ch)

    # ── 指令补全 ──

    def _complete_command(self):
        if self._input_target != 'cmd':
            return
        buf = self._input_buffer
        from ..commands import filter_commands
        prefix = buf.split()[0] if buf else ""
        if not prefix:
            return
        matches = filter_commands(prefix)
        if matches and matches[0].command != prefix:
            self._input_buffer = matches[0].command + " "
            self._update_panel_prompt(self._input_buffer)
            self._update_completion()

    def _update_hint_bar(self):
        from ..commands import get_command_tabs
        tabs = get_command_tabs()
        cmd = self._get_module('cmd')
        if isinstance(cmd, CommandPanel):
            cmd.update_hint_tabs(tabs)

    def _show_input_bar(self):
        target = self._input_target
        if target == 'cmd':
            cmd = self._get_module('cmd')
            if isinstance(cmd, CommandPanel):
                cmd.show_hint_bar()
        elif target == 'chat':
            chat = self._get_module('chat')
            if isinstance(chat, ChatPanel):
                chat.show_input_bar()

    def _hide_input_bar(self):
        cmd = self._get_module('cmd')
        if isinstance(cmd, CommandPanel):
            cmd.hide_hint_bar()
        chat = self._get_module('chat')
        if isinstance(chat, ChatPanel):
            chat.hide_input_bar()

    def _update_completion(self):
        if self._input_target != 'cmd':
            return
        cmd = self._get_module('cmd')
        if not isinstance(cmd, CommandPanel):
            return
        bar = cmd._bar()
        # 子菜单中不触发补全
        if bar and bar._nav_stack:
            return
        buf = self._input_buffer.strip()
        if not buf:
            cmd.exit_completion()
            return
        from ..commands import filter_commands
        prefix = buf.split()[0]
        matches = filter_commands(prefix)
        # 始终进入补全模式（匹配为空时显示"无匹配指令"提示）
        cmd.show_completion(matches)

    def _handle_enter(self):
        if self._input_target == 'cmd':
            cmd = self._get_module('cmd')
            if isinstance(cmd, CommandPanel):
                bar = cmd._bar()
                use_hint = (not self._input_buffer.strip() or
                            (bar and bar._mode == 'completion'))
                if use_hint and bar:
                    # 通用指令处理（子菜单钻入在 bar.enter() 中完成）
                    item = cmd.hint_enter()
                    if item is None:
                        # 已钻入子菜单
                        self._input_buffer = ''
                        self._update_panel_prompt(self._input_buffer)
                        return
                    # 普通指令 → 提交
                    self._input_buffer = item.command
                    self._submit_input()
                    return
        self._submit_input()

    def _hint_nav(self, direction: str):
        if self._input_target != 'cmd':
            return
        cmd = self._get_module('cmd')
        if isinstance(cmd, CommandPanel):
            cmd.hint_nav(direction)

    def _hint_back(self):
        if self._input_target != 'cmd':
            return
        cmd = self._get_module('cmd')
        if isinstance(cmd, CommandPanel):
            cmd.hint_back()

"""InputMixin — 输入提交、指令补全、频道切换"""

from __future__ import annotations

from ..panels import ChatPanel, CommandPanel
from ..panels.inventory import InventoryPanel
from ..panels.ai_chat import AIChatPanel
from ..panels.online import OnlineUsersPanel


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
        self.set_focus(None)

        if not text and self._input_target != 'login':
            if self._input_target == 'inventory':
                inv = self._get_module('inventory')
                if isinstance(inv, InventoryPanel):
                    inv.cancel_input()
            elif self._input_target == 'online':
                panel = self._get_module('online')
                if isinstance(panel, OnlineUsersPanel):
                    panel.on_input_submit("")
            return

        if self._input_target == 'login':
            if text:
                self._send_command(text)
        elif self._input_target == "chat":
            chat = self._get_module('chat')
            if isinstance(chat, ChatPanel):
                if chat._active_tab != "global":
                    # 私聊标签 → 发送私聊消息
                    self._send_private_chat(text, chat._active_tab)
                else:
                    self._send_chat(text, chat.current_channel)
            else:
                self._send_chat(text, 1)
        elif self._input_target == 'inventory':
            inv = self._get_module('inventory')
            if isinstance(inv, InventoryPanel):
                inv.on_input_submit(text)
        elif self._input_target == 'ai':
            ai_panel = self._get_module('ai')
            if isinstance(ai_panel, AIChatPanel):
                ai_panel.on_user_submit(text)
                if ai_panel.wants_insert:
                    self._enter_insert()
        elif self._input_target == 'online':
            panel = self._get_module('online')
            if isinstance(panel, OnlineUsersPanel):
                panel.on_input_submit(text)
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

    def _send_private_chat(self, text: str, target: str):
        self.app.network.send({"type": "private_chat", "target": target, "text": text})

    def _cycle_channel(self):
        chat = self._get_module('chat')
        if not isinstance(chat, ChatPanel):
            return
        # 如果有多个标签页，Tab 切换标签
        tabs = chat._tab_list()
        if len(tabs) > 1:
            chat.nav_tab_next()
            return
        # 否则切换世界/房间频道
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
        from ..protocol.commands import filter_commands
        prefix = buf.split()[0] if buf else ""
        if not prefix:
            return
        matches = filter_commands(prefix)
        if matches and matches[0].command != prefix:
            self._input_buffer = matches[0].command + " "
            self._update_panel_prompt(self._input_buffer)
            self._update_completion()

    def _update_hint_bar(self):
        from ..protocol.commands import get_command_tabs
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
        elif target == 'ai':
            ai_panel = self._get_module('ai')
            if isinstance(ai_panel, AIChatPanel):
                ai_panel.show_input_bar()
        elif target == 'online':
            panel = self._get_module('online')
            if isinstance(panel, OnlineUsersPanel):
                panel.show_input_bar()

    def _hide_input_bar(self):
        cmd = self._get_module('cmd')
        if isinstance(cmd, CommandPanel):
            cmd.hide_hint_bar()
        chat = self._get_module('chat')
        if isinstance(chat, ChatPanel):
            chat.hide_input_bar()
        ai_panel = self._get_module('ai')
        if isinstance(ai_panel, AIChatPanel):
            ai_panel.hide_input_bar()
        panel = self._get_module('online')
        if isinstance(panel, OnlineUsersPanel):
            panel.hide_input_bar()

    def _update_completion(self):
        if self._input_target != 'cmd':
            return
        cmd = self._get_module('cmd')
        if not isinstance(cmd, CommandPanel):
            return
        bar = cmd._bar()

        if bar and bar._nav_stack:
            # 子菜单中：用输入过滤当前子菜单项
            buf = self._input_buffer.strip()
            if not buf:
                if bar._mode == 'completion':
                    bar.exit_completion()
                return
            # 获取子菜单真实项（跳过 completion 模式的覆盖）
            sub_items = bar._tabs[bar._active_tab][1] if bar._tabs else []
            buf_lower = buf.lower()
            matches = [
                item for item in sub_items
                if self._match_sub_item(item, buf_lower)
            ]
            cmd.show_completion(matches)
            return

        buf = self._input_buffer.strip()
        if not buf:
            cmd.exit_completion()
            return
        from ..protocol.commands import filter_commands
        prefix = buf.split()[0]
        matches = filter_commands(prefix)
        # 始终进入补全模式（匹配为空时显示"无匹配指令"提示）
        cmd.show_completion(matches)

    @staticmethod
    def _match_sub_item(item, buf_lower: str) -> bool:
        """子菜单项匹配：label / command 尾段 / command 全匹配"""
        label = (item.label or '').lower()
        command = (item.command or '').lower()
        tail = command.split()[-1] if command else ''
        return (label.startswith(buf_lower)
                or tail.startswith(buf_lower)
                or command.startswith(buf_lower))

    def _handle_enter(self):
        if self._input_target == 'cmd':
            cmd = self._get_module('cmd')
            if isinstance(cmd, CommandPanel):
                bar = cmd._bar()
                use_hint = (not self._input_buffer.strip() or
                            (bar and (bar._mode == 'completion'
                                      or bar._nav_stack)))
                if use_hint and bar:
                    # 通用指令处理（子菜单钻入在 bar.enter() 中完成）
                    item = cmd.hint_enter()
                    if item is None:
                        # 已钻入子菜单 / 无匹配
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

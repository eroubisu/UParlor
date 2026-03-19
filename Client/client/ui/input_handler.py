"""InputMixin — 输入提交、指令补全、频道切换"""

from __future__ import annotations


class InputMixin:
    """输入处理 Mixin — 提供指令/聊天提交与 hint-bar 交互。"""

    # ── 输入提交 ──

    def _submit_input(self):
        text = self._input_buffer.strip()

        # 空 Enter + 指令面板 → 从 hint bar 选择
        if not text and self._input_target == 'cmd':
            self._clear_input_textarea()
            chain_done = self._hint_enter()
            if not self.vim.sticky and chain_done:
                self._close_insert_mode()
            return

        # 游戏面板: 空 Enter → 关闭
        if not text and self._input_target == 'game_board':
            if not self.vim.sticky:
                self._close_insert_mode()
            return

        # I(sticky): 发送后保持输入框打开; i(非sticky): 发送后关闭
        keep_insert = self.vim.sticky and self._input_target in ('chat', 'game_board', 'cmd')
        self._input_buffer = ""
        if not keep_insert:
            self._close_insert_mode()

        panel = self.get_module(self._input_target)

        # 空 Enter（非 login）→ cancel
        if not text and self._input_target != 'login':
            if panel and hasattr(panel, 'cancel_input'):
                panel.cancel_input()
            return

        # 委托面板处理
        if panel and hasattr(panel, 'on_input_submit'):
            panel.on_input_submit(text)
            if hasattr(panel, 'wants_insert') and panel.wants_insert:
                self._enter_insert()
        else:
            # 未知面板 → 作为指令发送
            if not text.startswith("/"):
                text = "/" + text
            self._send_command(text)

        # keep_insert 面板后处理
        if keep_insert:
            self._update_panel_prompt("")
            self._clear_input_textarea()
            if self._input_target == 'cmd':
                self._hint_filter('')

        if not self.logged_in:
            self._enter_insert()

    # ── 指令发送 ──

    def _send_command(self, text: str):
        self.app.send_command(text)

    def _close_insert_mode(self):
        """关闭输入模式：隐藏 prompt / input bar，回到 NORMAL。"""
        self._hide_panel_prompt()
        self._hide_input_bar()
        self.vim.enter_normal()
        self._update_mode_indicator()
        self.set_focus(None)

    def _cycle_channel(self):
        chat = self.get_module('chat')
        if not chat or not hasattr(chat, '_tab_list'):
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
        if self._input_target == 'login':
            login = self.get_module('login')
            if login and hasattr(login, 'nav_tab_next'):
                login.nav_tab_next()
            return
        buf = self._input_buffer
        from ..protocol.commands import filter_commands
        prefix = buf.split()[0] if buf else ""
        if not prefix:
            return
        matches = filter_commands(prefix)
        if matches and matches[0].command != ('/' + prefix if not prefix.startswith('/') else prefix):
            self._input_buffer = matches[0].command[1:] + " "  # 去掉 / 前缀
            self._update_panel_prompt(self._input_buffer)

    def _update_hint_bar(self):
        from ..protocol.commands import get_game_tabs
        game_tabs = get_game_tabs()
        board = self.get_module('game_board')
        if board and hasattr(board, 'update_game_tabs'):
            board.update_game_tabs(game_tabs)

    def _show_input_bar(self):
        panel = self.get_module(self._input_target)
        if panel and hasattr(panel, 'show_input_bar'):
            panel.show_input_bar()

    def _hide_input_bar(self):
        from ..ui.canvas import PaneWrapper
        for pw in self.canvas.query(PaneWrapper):
            w = pw.module_widget
            if w and hasattr(w, 'hide_input_bar'):
                w.hide_input_bar()

    def _clear_input_textarea(self):
        """清空当前面板的 InputTextArea 文本"""
        from ..widgets.input_bar import InputTextArea
        mod = self._focused_module()
        widget = self.get_module(mod) if mod else None
        if widget:
            try:
                ta = widget.query_one(InputTextArea)
                ta.clear()
            except Exception:
                pass

    def _handle_enter(self):
        self._submit_input()

    def _hint_nav(self, direction: str):
        board = self.get_module('game_board')
        if board and hasattr(board, '_hint_bar'):
            bar = board._hint_bar()
            if bar:
                getattr(bar, f'nav_{direction}')()

    def _hint_back(self):
        board = self.get_module('game_board')
        if board and hasattr(board, '_hint_bar'):
            bar = board._hint_bar()
            if bar:
                bar.back()

    def _hint_filter(self, text: str):
        """根据输入文本跳转 hint bar 选中项"""
        board = self.get_module('game_board')
        if board and hasattr(board, '_hint_bar'):
            bar = board._hint_bar()
            if bar:
                bar.filter_items(text.strip().lstrip('/'))

    def _hint_tab_complete(self):
        """Tab 补全：将当前高亮项的名称填入过滤缓冲区"""
        board = self.get_module('game_board')
        if not board or not hasattr(board, '_hint_bar'):
            return
        bar = board._hint_bar()
        if not bar:
            return
        items = bar._current_items()
        if items and bar._selected_idx < len(items):
            name = bar._item_name(items[bar._selected_idx])
            self._cmd_filter_buf = name
            bar.filter_items(name)

    def _hint_enter(self) -> bool:
        """从 hint bar 选择当前高亮项并执行。

        返回 True 表示指令链完成（叶子指令已执行），
        False 表示进入了本地子菜单、未选中任何项。
        """
        board = self.get_module('game_board')
        if board and hasattr(board, '_hint_bar'):
            bar = board._hint_bar()
            if bar:
                item = bar.enter()
                if item:
                    confirm = getattr(item, 'confirm', '')
                    if confirm:
                        from dataclasses import replace
                        confirmed = replace(item, confirm='')
                        bar._push_stack()
                        bar._tabs = [(confirm, [confirmed])]
                        bar._active_tab = 0
                        bar._selected_idx = 0
                        bar._scroll_offset = 0
                        bar._filter_text = ''
                        bar._refresh_display()
                        self._cmd_filter_buf = ''
                        return False
                    cmd = item.command
                    self._cmd_filter_buf = ''
                    if bar._nav_stack:
                        bar.reset_to_root()
                    self._send_command(cmd)
                    return True
                else:
                    self._cmd_filter_buf = ''
        return False

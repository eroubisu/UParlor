"""
麻将客户端处理器 — 处理所有麻将特有的事件和指令

从 tui_app.py 剥离的纯逻辑代码：
  - hand_update: 更新手牌/听牌状态
  - action_prompt: 他家打牌时的动作提示
  - self_action_prompt: 自摸/暗杠/加杠提示
  - win_animation: 和了动画（逐行延迟显示）
"""

from __future__ import annotations

from ..game_handler import (
    GameClientHandler,
    GameHandlerContext,
    CommandInfo,
    register_handler,
)


class MahjongHandler:
    """麻将游戏客户端处理器"""

    game_type = "mahjong"

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        if event == "hand_update":
            return self._on_hand_update(data, ctx)
        elif event == "action_prompt":
            return self._on_action_prompt(data, ctx)
        elif event == "self_action_prompt":
            return self._on_self_action_prompt(data, ctx)
        elif event == "win_animation":
            return self._on_win_animation(data, ctx)
        return False

    def get_available_commands(self, location: str) -> list[CommandInfo]:
        cmds = []
        if location.startswith("mahjong"):
            cmds.append(CommandInfo("/d <牌>", "打牌", "打出指定的牌，如 /d 5m"))
            cmds.append(CommandInfo("/next", "下一局", "和了后开始下一局"))
        return cmds

    def on_enter_game(self, ctx: GameHandlerContext) -> None:
        pass

    def on_leave_game(self, ctx: GameHandlerContext) -> None:
        pass

    # ── 事件处理 ──

    def _on_hand_update(self, data: dict, ctx: GameHandlerContext) -> bool:
        game_data = {
            "hand": data.get("hand"),
            "drawn": data.get("drawn"),
            "tenpai": data.get("tenpai_analysis"),
            "need_discard": data.get("need_discard", False),
        }
        ctx.status_update("mahjong", game_data)
        return True

    def _on_action_prompt(self, data: dict, ctx: GameHandlerContext) -> bool:
        actions = data.get("actions", {})
        tile = data.get("tile", "")
        from_player = data.get("from_player", "")

        parts = []
        idx = 1
        for action_name, label in [("ron", "荣和"), ("pon", "碰"), ("kan", "杠")]:
            if action_name in actions:
                parts.append(f"[{idx}]{label}")
                idx += 1
        if "chi" in actions:
            chi_opts = actions["chi"]
            if isinstance(chi_opts, list):
                for c in chi_opts:
                    parts.append(f"[{idx}]吃{c}")
                    idx += 1
            else:
                parts.append(f"[{idx}]吃")
                idx += 1
        parts.append(f"[{idx}]跳过")
        bar_text = f"{from_player}打出 {tile}: {' '.join(parts)}"
        ctx.cmd_set_action_bar(bar_text)
        return True

    def _on_self_action_prompt(self, data: dict, ctx: GameHandlerContext) -> bool:
        actions = data.get("actions", {})

        parts = []
        idx = 1
        if "tsumo" in actions:
            parts.append(f"[{idx}]自摸"); idx += 1
        if "riichi" in actions:
            parts.append(f"[{idx}]立直"); idx += 1
        if "ankan" in actions:
            for tiles in actions["ankan"]:
                parts.append(f"[{idx}]暗杠{tiles}"); idx += 1
        if "kakan" in actions:
            for tile in actions["kakan"]:
                parts.append(f"[{idx}]加杠{tile}"); idx += 1
        parts.append(f"[{idx}]跳过")
        bar_text = " ".join(parts)
        ctx.cmd_set_action_bar(bar_text)
        return True

    def _on_win_animation(self, data: dict, ctx: GameHandlerContext) -> bool:
        winner = data.get("winner", "?")
        win_type = data.get("win_type", "")
        tile = data.get("tile", "")
        loser = data.get("loser", "")
        yakus = data.get("yakus", [])
        is_yakuman = data.get("is_yakuman", False)
        han = data.get("han", 0)
        fu = data.get("fu", 0)
        score = data.get("score", 0)

        # 标题行
        if win_type == "tsumo":
            header = f"[b]【{winner} 自摸】[/b] [{tile}]"
        else:
            header = f"[b]【{winner} 荣和】[/b] [{tile}]"
            if loser:
                header += f" (放铳: {loser})"
        ctx.cmd_add_line(header)

        # 役种（逐行延迟写入 Widget）
        delay = 0.8
        for i, yaku in enumerate(yakus):
            yaku_name = yaku[0] if len(yaku) > 0 else ""
            yaku_han = yaku[1] if len(yaku) > 1 else 0
            is_yk = yaku[2] if len(yaku) > 2 else False
            if is_yk:
                text = f"  ★ {yaku_name} (役满)"
            else:
                text = f"  · {yaku_name} ({yaku_han}番)"
            # State 立即写入
            ctx.state.cmd.add_line(text)
            # Widget 延迟写入（动画效果）
            ctx.set_timer(delay * (i + 1), lambda t=text: ctx.cmd_widget_add_line(t))

        # 点数
        final_delay = delay * (len(yakus) + 1)
        if is_yakuman:
            score_text = f"\n[b]【点数】役满 {score}点[/b]"
        else:
            score_text = f"\n[b]【点数】{han}番{fu}符 = {score}点[/b]"
        ctx.state.cmd.add_line(score_text)
        ctx.set_timer(final_delay, lambda: ctx.cmd_widget_add_line(score_text))

        next_text = "\n输入 /next 开始下一局"
        ctx.state.cmd.add_line(next_text)
        ctx.set_timer(final_delay + 0.4, lambda: ctx.cmd_widget_add_line(next_text))
        return True


register_handler(MahjongHandler())

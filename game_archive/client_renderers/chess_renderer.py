"""
象棋渲染器 — 国际象棋棋盘/状态渲染（使用 Unicode 棋子 + Rich Table 对齐）
"""

from __future__ import annotations

from textual.widgets import RichLog
from rich.table import Table
from ..game_registry import register_renderer


# Unicode 棋子映射
_PIECE_ICONS = {
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
}


class ChessRenderer:
    """国际象棋渲染器"""

    game_type = "chess"

    def render_board(self, log: RichLog, room_data: dict) -> None:
        log.clear()
        board = room_data.get("board")
        if not board:
            self._render_player_list(log, room_data)
            return

        last_squares = room_data.get("last_move_squares") or []
        is_2d = isinstance(board[0], list)

        table = Table(show_header=True, box=None, padding=(0, 1), show_edge=False)
        table.add_column("", justify="right", width=1, no_wrap=True)
        for col in "abcdefgh":
            table.add_column(col, justify="center", width=2, no_wrap=True)

        for rank in range(8, 0, -1):
            cells = []
            for file_idx in range(8):
                cell = board[8 - rank][file_idx] if is_2d else board[(8 - rank) * 8 + file_idx]
                sq = chr(ord('a') + file_idx) + str(rank)
                if cell:
                    icon = _PIECE_ICONS.get(cell, cell)
                    if sq in last_squares:
                        cells.append(f"[reverse #E8E8E8]{icon}[/]")
                    elif cell.isupper():
                        cells.append(f"[bold #E8E8E8]{icon}[/]")
                    else:
                        cells.append(f"[#808080]{icon}[/]")
                else:
                    dot = "·" if (rank + file_idx) % 2 == 1 else "·"
                    cells.append(f"[#454545]{dot}[/]")
            table.add_row(str(rank), *cells)

        log.write(table)

    def render_board_waiting(self, log: RichLog, room_data: dict) -> None:
        self.render_board(log, room_data)

    def render_status(self, log: RichLog, game_data: dict) -> None:
        log.clear()
        players = game_data.get("players", {})
        current_turn = game_data.get("current_turn")
        time_display = game_data.get("time_display", {})
        move_history = game_data.get("move_history", [])
        move_count = game_data.get("move_count", 0)
        draw_offer = game_data.get("draw_offer_from")

        colors = ["白", "黑"]
        for side in (0, 1):
            name = players.get(side) or players.get(str(side), "?")
            time_str = time_display.get(side, time_display.get(str(side), ""))
            turn_mark = " ◀" if current_turn == side else ""
            log.write(f"{colors[side]}: {name}  {time_str}{turn_mark}")

        log.write("─" * 20)

        if move_history:
            log.write(f"[b]棋谱[/b] ({move_count}步)")
            for i in range(0, len(move_history), 2):
                move_num = i // 2 + 1
                white_san = move_history[i][0] if i < len(move_history) else ""
                black_san = move_history[i + 1][0] if i + 1 < len(move_history) else ""
                log.write(f"  {move_num}. {white_san}  {black_san}")
        else:
            log.write("[dim]等待走棋...[/dim]")

        if draw_offer is not None:
            side_name = colors[draw_offer] if draw_offer in (0, 1) else "?"
            log.write(f"\n[b]{side_name}方提出和棋[/b]")

    def _render_player_list(self, log: RichLog, room_data: dict) -> None:
        """等待中的房间：仅显示玩家列表"""
        players = room_data.get("players", {})
        if isinstance(players, dict):
            colors = ["白", "黑"]
            for key, name in players.items():
                label = colors[int(key)] if str(key).isdigit() and int(key) < 2 else f"#{key}"
                log.write(f"{label}: {name}")
        elif isinstance(players, list):
            for p in players:
                name = p.get("name", "空位") if isinstance(p, dict) else str(p)
                log.write(name)


register_renderer(ChessRenderer())

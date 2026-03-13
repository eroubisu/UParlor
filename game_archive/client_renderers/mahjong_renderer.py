"""
麻将渲染器 — 从 tui_widgets.py 提取的麻将棋盘/状态渲染逻辑
"""

from __future__ import annotations

from textual.widgets import RichLog
from ..game_registry import register_renderer


# ── 牌面样式（游戏内容可使用彩色） ──

_SUIT_STYLES = {
    '万': '#E85D5D',    # 红色
    '筒': '#5D8DE8',    # 蓝色
    '索': '#5DE88D',    # 绿色
    '风': '#D0D0D0',    # 浅灰
    '三元': '#E8C85D',  # 金色
}


def _tile_suit(tile: str) -> str:
    if '万' in tile:
        return '万'
    if '筒' in tile:
        return '筒'
    if '索' in tile:
        return '索'
    if tile in ('东', '南', '西', '北'):
        return '风'
    if tile in ('中', '发', '白'):
        return '三元'
    return ''


def _styled_tile(tile: str) -> str:
    suit = _tile_suit(tile)
    color = _SUIT_STYLES.get(suit, '')
    return f"[{color}]{tile}[/]" if color else tile


class MahjongRenderer:
    """麻将游戏渲染器"""

    game_type = "mahjong"

    def render_board(self, log: RichLog, room_data: dict) -> None:
        log.clear()
        state = room_data.get("state", "waiting")
        positions = room_data.get("positions", room_data.get("players", []))
        room_id = room_data.get("room_id", "?")
        round_wind = room_data.get("round_wind", "")
        round_number = room_data.get("round_number", 0)
        honba = room_data.get("honba", 0)

        header = f"房间:{room_id}"
        if state == "playing" and round_wind:
            header += f"  {round_wind}{round_number + 1}局"
            if honba:
                header += f" {honba}本场"
        else:
            header += f"  {state}"
        log.write(header)

        dora = room_data.get("dora_indicators", [])
        remaining = room_data.get("deck_remaining", room_data.get("remaining_tiles", "?"))
        info_parts = []
        if dora:
            info_parts.append(f"宝牌:{' '.join(dora)}")
        info_parts.append(f"剩余:{remaining}")
        riichi_sticks = room_data.get("riichi_sticks", 0)
        if riichi_sticks:
            info_parts.append(f"立直棒:{riichi_sticks}")
        log.write("  ".join(info_parts))
        log.write("─" * 24)

        for i, p in enumerate(positions):
            name = p.get("name", f"空位{i}")
            score = p.get("score", 25000)
            wind = p.get("wind", ["东", "南", "西", "北"][i] if i < 4 else "?")
            is_riichi = p.get("is_riichi", p.get("riichi", False))
            is_turn = p.get("is_turn", False)
            is_dealer = p.get("is_dealer", False)

            dealer_mark = "庄" if is_dealer else "　"
            riichi_mark = " [b]立[/b]" if is_riichi else ""
            turn_mark = " ◀" if is_turn else ""
            log.write(f"{wind}{dealer_mark} {name} {score}{riichi_mark}{turn_mark}")

            melds = p.get("melds", [])
            if melds:
                meld_strs = []
                for m in melds:
                    mtype = m.get("type", "")
                    tiles = m.get("tiles", [])
                    if mtype == "concealed_kong":
                        meld_strs.append("[暗杠]")
                    else:
                        meld_strs.append(' '.join(tiles))
                log.write(f"  副露: {' | '.join(meld_strs)}")

            discards = p.get("discards", [])
            if discards:
                for row_start in range(0, len(discards), 6):
                    chunk = discards[row_start:row_start + 6]
                    prefix = "  牌河: " if row_start == 0 else "        "
                    log.write(f"{prefix}{' '.join(chunk)}")

            if i < len(positions) - 1:
                log.write("")

    def render_board_waiting(self, log: RichLog, room_data: dict) -> None:
        self.render_board(log, room_data)

    def render_status(self, log: RichLog, game_data: dict) -> None:
        hand = game_data.get("hand", [])
        drawn = game_data.get("drawn")
        tenpai = game_data.get("tenpai")
        need_discard = game_data.get("need_discard", False)

        if not hand:
            return

        log.clear()

        log.write("[b]手牌[/b]")
        log.write("─" * 16)

        main_hand = hand[:-1] if drawn and len(hand) > 1 else hand
        for tile in main_hand:
            log.write(f"  {_styled_tile(tile)}")

        if drawn:
            log.write("─" * 8)
            log.write(f"  {_styled_tile(drawn)} ← [b]摸牌[/b]")

        if tenpai:
            log.write("")
            if isinstance(tenpai, dict):
                is_tenpai = tenpai.get('is_tenpai', False)
                if is_tenpai:
                    waiting = tenpai.get('waiting', [])
                    if waiting:
                        log.write("[b]听牌:[/b]")
                        for w in waiting:
                            if isinstance(w, (list, tuple)) and len(w) >= 2:
                                log.write(f"  {_styled_tile(str(w[0]))} ({w[1]}张)")
                            else:
                                log.write(f"  {_styled_tile(str(w))}")
                    d2t = tenpai.get('discard_to_tenpai', {})
                    if d2t and need_discard:
                        log.write("")
                        log.write("[b]打牌听牌:[/b]")
                        for discard_tile, waits in d2t.items():
                            wait_strs = []
                            for w in waits:
                                if isinstance(w, (list, tuple)) and len(w) >= 2:
                                    wait_strs.append(f"{w[0]}({w[1]})")
                                else:
                                    wait_strs.append(str(w))
                            log.write(f"  打{_styled_tile(discard_tile)} → {', '.join(wait_strs)}")
            elif isinstance(tenpai, list):
                waits = ", ".join(str(t) for t in tenpai)
                log.write(f"[b]听:[/b] {waits}")

        if need_discard:
            log.write("")
            log.write("[b]请出牌[/b] (d+牌名)")


register_renderer(MahjongRenderer())

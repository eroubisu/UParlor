"""game_checks.py — 房间制游戏通用状态读取器与断言

从 app.screen.state.game_board.room_data 读取游戏状态，
提供 get_* 读取函数和 assert_* 断言函数。
"""

from __future__ import annotations


def _get_screen(app):
    from client.ui.screen import GameScreen
    screen = app.screen
    return screen if isinstance(screen, GameScreen) else None


def get_room_data(app) -> dict:
    """读取当前 room_data，无则返回空 dict。"""
    screen = _get_screen(app)
    if not screen:
        return {}
    return getattr(screen.state.game_board, 'room_data', {}) or {}


def get_room_state(app) -> str:
    """返回 room_state: 'lobby' | 'waiting' | 'playing' | 'finished' 等。"""
    return get_room_data(app).get('room_state', '')


def get_game_type(app) -> str:
    """返回 game_type: 'holdem' | 'blackjack' | 'doudizhu' 等。"""
    return get_room_data(app).get('game_type', '')


def get_current_player(app) -> str:
    """返回当前操作玩家名。"""
    return get_room_data(app).get('current_player', '')


def get_winners(app) -> list:
    """返回 winners 列表（holdem 格式: [{'name':..., 'amount':...}]）。"""
    return get_room_data(app).get('winners', [])


def get_results(app) -> dict:
    """返回 results dict（blackjack 格式: {player: {outcome:..., payout:...}}）。"""
    return get_room_data(app).get('results', {})


def is_my_turn(app) -> bool:
    """当前操作者是否为我 — 自动根据 game_type 选择判断策略。

    - chess: viewer_seat == current_seat
    - mahjong: my_turn boolean
    - 其他: current_player == username
    """
    rd = get_room_data(app)
    gt = rd.get('game_type', '')
    if gt == 'chess':
        vs = rd.get('viewer_seat')
        cs = rd.get('current_seat')
        return vs is not None and vs == cs
    if gt == 'mahjong':
        return bool(rd.get('my_turn'))
    username = getattr(app, '_e2e_username', '')
    return rd.get('current_player', '') == username


def is_game_over(app) -> bool:
    """游戏是否结束。"""
    return get_room_state(app) in ('finished', 'waiting')


# ── 断言 ──

def assert_room_state(app, expected: str):
    actual = get_room_state(app)
    assert actual == expected, f"expected room_state={expected!r}, got {actual!r}"


def assert_game_type(app, expected: str):
    actual = get_game_type(app)
    assert actual == expected, f"expected game_type={expected!r}, got {actual!r}"


def assert_in_game(app, game_id: str):
    """断言当前在指定游戏中（game_type 匹配）。"""
    assert_game_type(app, game_id)


def assert_playing(app):
    """断言游戏正在进行。"""
    assert_room_state(app, 'playing')


def get_doc(app) -> str:
    """返回 room_data 中的 doc 文本。"""
    return get_room_data(app).get('doc', '')

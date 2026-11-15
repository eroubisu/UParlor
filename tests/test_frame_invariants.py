"""画面不变量检查器自己要能抓到违规：拿真实画面做手脚，应当逐条报出来。"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import frame_invariants as fi  # noqa: E402
from client.protocol.renderer import RENDERER_REGISTRY  # noqa: E402
from server.games.baseball.room import BaseballRoom, log_violations  # noqa: E402

SIZE = (46, 19)


def _call_room(verdict: str = "") -> BaseballRoom:
    room = BaseballRoom("test", ["alice", "bob"], None)
    room.rng = random.Random(11)
    room.start()
    room.verdict = verdict
    return room


def _board(room: BaseballRoom):
    data = room.get_game_data(viewer=room.fielding_player())
    text = fi._dump(RENDERER_REGISTRY["baseball"].render_board(
        data, None, *SIZE)["board"], SIZE[0])
    return data, text


def _codes(data, text, state=None):
    problems = fi.board_problems(data, text, *SIZE, state or fi._RunState())
    return {code for code, _ in problems}


def test_a_real_board_with_a_verdict_and_lights_passes():
    data, text = _board(_call_room("safe"))

    assert _codes(data, text) == set()


def test_missing_ready_lights_in_the_call_phase_are_reported():
    data, text = _board(_call_room("safe"))
    lines = text.split("\n")
    lights = next(i for i, line in enumerate(lines) if "投" in line and "│" in line)
    lines[lights] = "  │" + " " * 26 + "│"

    codes = _codes(data, "\n".join(lines))

    assert "lights-missing-in-call" in codes and "slot-content" in codes


def test_stray_text_inside_the_box_is_reported():
    data, text = _board(_call_room())
    lines = text.split("\n")
    lines[4] = "  │   多余文字" + " " * 14 + "│"

    assert "stray-text-in-box" in _codes(data, "\n".join(lines))


def test_a_base_name_that_moves_between_frames_is_reported():
    state = fi._RunState()
    data, text = _board(_call_room())
    assert _codes(data, text, state) == set()
    moved = text.replace("二垒", "  二垒", 1)

    assert "base-name-moved" in _codes(data, moved, state)


def test_undeclared_glyphs_and_markup_leaks_are_reported():
    data, text = _board(_call_room())
    dirty = text.replace("·", "◇", 1).replace("三垒", "[#50b070]三垒", 1)

    codes = _codes(data, dirty)

    assert {"undeclared-glyph", "markup-leak"} <= codes


def test_status_pages_must_keep_their_row_counts():
    state = fi._RunState()
    room = _call_room()
    data = room.get_game_data(viewer=room.fielding_player())
    assert fi.status_problems(data, state) == []
    state.status_rows["局面"] += 1

    assert any(code == "status-rows-moved"
               for code, _ in fi.status_problems(data, state))


def test_log_rules_name_each_kind_of_violation():
    assert log_violations("封杀 一垒 打者 1出局") == []
    assert log_violations("封杀，一垒") == ["含中文标点"]
    assert log_violations("封杀  一垒") == ["空格不规范"]
    assert log_violations("甲 " * 40) == ["超过 70 列", "空格不规范"]
    assert log_violations("甲\n乙") == ["不是单行"]


def test_a_short_simulated_match_satisfies_every_invariant():
    report = fi.check_match(seed=3, innings=1, sizes=(SIZE,))

    assert report.games == 1 and report.frames > 50
    assert report.ok, dict(report.counts)

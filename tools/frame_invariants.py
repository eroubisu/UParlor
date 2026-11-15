"""棒球画面的确定性不变量检查：模拟整局比赛，逐帧核对"位置固定"等写在规范里的规则。

规范里的规则（东西都在原位、亮不亮都占同样空间、日志写法……）以前只靠文字和人记，
两次被违反都是用户实机发现的。这里把它们变成每帧都跑的检查：

    python tools/frame_invariants.py --games 3 --innings 1

不带任何第三方依赖（只用 rich 和项目本身），`tools/check.py` 会跑一个很短的版本。
检查的是"画面和判定的对应关系"，期望值尽量来自产品代码自己（`live_slot_segments`、
`Infield.slot_rows()`、`log_violations()`），而不是在这里再抄一份规则。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import random
import re
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _path in (ROOT / "Client", ROOT / "Server"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rich.cells import cell_len  # noqa: E402
from rich.console import Console  # noqa: E402

import client.games  # noqa: E402,F401  注册渲染器
from client.config import GAME_TEXT_GLYPHS  # noqa: E402
from client.games.baseball.diamond import Infield, live_slot_segments  # noqa: E402
from client.games.baseball.view import Board  # noqa: E402
from client.protocol.renderer import RENDERER_REGISTRY  # noqa: E402
from server import chat_server as chat_server_module  # noqa: E402
from server.games.baseball.room import log_violations  # noqa: E402
from server.player.manager import (  # noqa: E402
    PlayerManager, get_default_user_template,
)

DEFAULT_SIZES = ((46, 19), (80, 30))
STATUS_COLS = 38
_MARKUP = re.compile(r"\[/?[#a-zA-Z][^\]]*\]")
_TABLE_LINES = ("客 ", "主 ")     # 结算的逐局比分表按列对齐，允许连续空格


@dataclass
class Violation:
    code: str
    detail: str
    seed: int
    frame: int


@dataclass
class Report:
    frames: int = 0
    games: int = 0
    counts: Counter = field(default_factory=Counter)
    samples: dict[str, Violation] = field(default_factory=dict)

    def add(self, violation: Violation) -> None:
        self.counts[violation.code] += 1
        self.samples.setdefault(violation.code, violation)

    @property
    def ok(self) -> bool:
        return not self.counts


@dataclass
class _RunState:
    """跨帧才能判断的不变量（行数、垒名列都不许在比赛中变）。"""

    status_rows: dict[str, int] = field(default_factory=dict)
    base_columns: dict[tuple, int] = field(default_factory=dict)


def _dump(renderable, width: int) -> str:
    if renderable is None:
        return ""
    import io

    console = Console(width=width, record=True, color_system=None,
                      file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def _cell_slice(line: str, start: int, stop: int) -> str:
    out, column = [], 0
    for char in line:
        if start <= column < stop:
            out.append(char)
        column += cell_len(char)
    return "".join(out)


def _is_cjk(char: str) -> bool:
    return "\u2e80" <= char <= "\u9fff" or "\uff00" <= char <= "\uffef"


# ── 单帧检查 ──


Problems = list[tuple[str, str]]


def _surface_problems(body: list[str], width: int) -> Problems:
    """每一行：不超宽、没有富文本标记泄露、字形都登记过。"""
    problems: Problems = []
    declared = RENDERER_REGISTRY["baseball"].glyphs
    for index, line in enumerate(body):
        if cell_len(line) > width:
            problems.append(("board-overflow", f"第{index}行 {cell_len(line)}>{width}"))
        if _MARKUP.search(line):
            problems.append(("markup-leak", repr(line)))
        for char in line:
            if (ord(char) > 127 and not _is_cjk(char) and cell_len(char) == 1
                    and char not in declared and char not in GAME_TEXT_GLYPHS):
                problems.append(("undeclared-glyph", f"U+{ord(char):04X}"))
    return problems


def _slot_problems(board: Board, infield: Infield, body: list[str]) -> Problems:
    """方框里：每个槽在自己的行上写着产品代码算出来的内容，其余行全空；准备阶段灯必须在。"""
    problems: Problems = []
    expected = ["".join(piece for piece, _ in slot)
                for slot in live_slot_segments(board)]
    rows = infield.slot_rows()
    slot_lines = {row + 1: index for index, row in enumerate(rows)
                  if row is not None}
    for line_index in range(2, infield.rows + 2):
        inner = _cell_slice(body[line_index], infield.left + 1,
                            infield.right).strip()
        slot = slot_lines.get(line_index)
        if slot is None:
            if inner:
                problems.append(("stray-text-in-box", f"行{line_index} {inner!r}"))
        elif inner != expected[slot].strip():
            problems.append(("slot-content",
                             f"槽{slot} 应为 {expected[slot]!r} 实为 {inner!r}"))
    if board.phase == "call" and slot_lines:
        middle = _cell_slice(body[rows[2] + 1], infield.left + 1, infield.right)
        if "投" not in middle or "打" not in middle:
            problems.append(("lights-missing-in-call",
                             f"verdict={board.verdict or '-'}"))
    return problems


def _corner_problems(body: list[str], infield: Infield, width: int,
                     height: int, state: _RunState) -> Problems:
    """四个垒名：有没有传球距离都在同一列。"""
    problems: Problems = []
    for line, names in ((body[0], ("三垒", "二垒")),
                        (body[infield.rows + 3], ("本垒", "一垒"))):
        for name in names:
            if name not in line:
                problems.append(("base-name-missing", name))
                continue
            column = cell_len(line[:line.index(name)])
            first = state.base_columns.setdefault((width, height, name), column)
            if column != first:
                problems.append(("base-name-moved", f"{name} {column}≠{first}"))
    return problems


def _track_problems(body: list[str], infield: Infield) -> Problems:
    """方框下面的三条固定行：前缀齐全、左竖线同一列。"""
    tracks = body[infield.rows + 4:]
    if len(tracks) != 3 or not all(
            line.lstrip().startswith(prefix)
            for line, prefix in zip(tracks, ("投打", "外野", "传球"))):
        return [("track-rows", repr(tracks))]
    columns = {cell_len(line[:line.index("│")]) for line in tracks
               if "│" in line}
    if len(columns) != 1:
        return [("track-left-bar-misaligned", str(sorted(columns)))]
    return []


def board_problems(data: dict, text: str, width: int, height: int,
                   state: _RunState) -> Problems:
    """一张棋盘（某一方视角、某个尺寸）违反的规则：[(代码, 细节)]。"""
    lines = text.split("\n")
    body = lines[:height]
    if len(body) < height or any(line.strip() for line in lines[height:]):
        return [("board-height", f"行数不是 {height}")]
    board = Board.parse(data)
    infield = Infield(board, None, width, height)
    return [
        *_surface_problems(body, width),
        *_slot_problems(board, infield, body),
        *_corner_problems(body, infield, width, height, state),
        *_track_problems(body, infield),
    ]


def status_problems(data: dict, state: _RunState) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    content = RENDERER_REGISTRY["baseball"].render_status(data, None)
    for title, page in content.pages:
        page_lines = _dump(page, 40).split("\n")[:-1]
        rows = state.status_rows.setdefault(title, len(page_lines))
        if len(page_lines) != rows:
            problems.append(("status-rows-moved",
                             f"{title} {len(page_lines)}≠{rows}"))
        for line in page_lines:
            if cell_len(line) > STATUS_COLS:
                problems.append(("status-overflow", f"{title} {line!r}"))
            if _MARKUP.search(line):
                problems.append(("markup-leak", f"status {line!r}"))
    return problems


def message_problems(text: str) -> list[tuple[str, str]]:
    if text.startswith(_TABLE_LINES):
        return []
    return [("log-rule", f"{problem}：{text!r}")
            for problem in log_violations(text)]


# ── 整局模拟（真人由机器人的决策代打，走和玩家一样的指令） ──


class _Timers:
    queue: list = []

    def __init__(self, delay, fn, args=(), kwargs=None):
        self._entry = (fn, args, delay)

    def start(self) -> None:
        _Timers.queue.append(self._entry)

    def cancel(self) -> None:
        if self._entry in _Timers.queue:
            _Timers.queue.remove(self._entry)


class _Match:
    def __init__(self, innings: int) -> None:
        self.server = chat_server_module.ChatServer()
        self.lobby = self.server.lobby_engine
        self.engine = self.lobby._ensure_engine("baseball")
        self.scheduler = self.server.bot_schedulers["baseball"]
        self.human = "human"
        self.innings = innings
        self.now = [1000.0]
        self.received: list[dict] = []
        self.server.send_to_player = (
            lambda name, message: self.received.append(message)
            if name == self.human else None)
        self.data = get_default_user_template(name=self.human,
                                              password_hash="x")
        self.data.pop("password_hash", None)
        self.lobby.register_player(self.human, self.data)
        self.lobby.set_player_location(self.human, "baseball")

    @property
    def room(self):
        return self.engine.get_player_room(self.human)

    def command(self, name: str, arg: str = "") -> None:
        result = self.engine.handle_command(
            self.lobby, self.human, self.data, name, arg)
        self.received.extend(result.get("send_to_caller", []))
        self.received.extend(result.get("send_to_players", {}).get(
            self.human, []))
        for task in result.get("schedule", []):
            scheduler = self.server.bot_schedulers.get(task.get("game_id", ""))
            if scheduler:
                scheduler.handle_schedule(task)

    def step(self) -> bool:
        if not _Timers.queue:
            return False
        fn, args, delay = _Timers.queue.pop(0)
        self.now[0] += delay
        fn(*args)
        return True

    def start(self) -> None:
        self.command("create", json.dumps({"innings": self.innings}))
        self.room.clock = lambda: self.now[0]
        self.command("bot")
        self.command("start")
        while self.step():
            pass


def _human_acts(match: _Match, rng: random.Random) -> bool:
    """真人这一方的一步（和测试里"打一整场"同一套决策）；没有可做的返回 False。"""
    room, human = match.room, match.human
    bot = match.scheduler._bot
    if room.armed and room.fielding_player() == human:
        match.command("release")
        return True
    owner = room.decision_owner()
    if room.is_bot(owner):
        return False
    if owner == human:
        if room.phase == "call":
            if room.fielding_player() == human:
                shift = bot._pick_shift(room)
                if shift != "standard":
                    match.command("shift", shift)
                call = bot._pick_pitch(room)
                match.command("pitch", f"{call.pitch_type} {call.band} "
                                       f"{call.effort} {call.hold}")
            else:
                call = bot._pick_swing(room)
                match.command("swing", f"{call.guess} {call.swing} {call.steal}")
        elif room.phase == "tag":
            match.command("run", "stop" if room.outs >= 2 else "go")
        return True
    if room.phase == "flight":
        flight = room.flight
        if room.fielding_player() == human:
            match.command("field", "right"
                          if flight.fielder.pos < flight.estimate() else "left")
            if rng.random() < 0.6:
                match.command("jump")
        elif room.bases:
            match.command("run", "go")
        return True
    if room.phase == "ground":
        ground = room.ground
        if room.fielding_player() == human:
            if not room.at_ball():
                match.command("field", "right"
                              if ground.fielder.pos < ground.ball else "left")
            else:
                options = room.throw_options()
                match.command("throw", rng.choice(options).base)
        return True
    return False


@contextlib.contextmanager
def _patched_server():
    _Timers.queue = []
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(
            chat_server_module, "ChatLogManager", mock.Mock))
        stack.enter_context(mock.patch.object(
            chat_server_module, "DMLogManager", mock.Mock))
        stack.enter_context(mock.patch.object(
            PlayerManager, "save_player_data", mock.Mock()))
        stack.enter_context(mock.patch.object(threading, "Timer", _Timers))
        yield


def check_match(seed: int, innings: int, sizes=DEFAULT_SIZES,
                report: Report | None = None) -> Report:
    """模拟一整局并逐帧检查；返回（或累加进）报告。"""
    report = report or Report()
    renderer = RENDERER_REGISTRY["baseball"]
    state = _RunState()
    random.seed(seed)
    rng = random.Random(seed)
    with _patched_server():
        match = _Match(innings)
        match.start()
        match.room.rng.seed(seed)
        seen = 0
        in_match_log = False
        for frame in range(20000):
            room = match.room
            if room is None or room.phase == "finished":
                break
            acted = _human_acts(match, rng)
            problems: list[tuple[str, str]] = []
            for viewer in room.players:
                data = room.get_game_data(viewer=viewer)
                if data.get("phase") is None:
                    continue
                for width, height in sizes:
                    text = _dump(renderer.render_board(
                        data, None, width, height)["board"], width)
                    problems += board_problems(data, text, width, height, state)
                problems += status_problems(data, state)
            for message in match.received[seen:]:
                if message.get("type") != "game":
                    continue
                text = message.get("text", "")
                in_match_log = in_match_log or text.startswith("开赛")
                if in_match_log:
                    for line in text.split("\n"):
                        problems += message_problems(line)
            seen = len(match.received)
            for code, detail in problems:
                report.add(Violation(code, detail, seed, frame))
            report.frames += 1
            if not match.step() and not acted:
                report.add(Violation("stuck", f"阶段 {room.phase}", seed, frame))
                break
        else:
            report.add(Violation("no-end", f"阶段 {match.room.phase}", seed, 20000))
        if match.room is not None and match.room.phase != "finished":
            report.add(Violation("unfinished", match.room.phase, seed, report.frames))
    report.games += 1
    return report


def _parse_sizes(text: str):
    return tuple(tuple(int(part) for part in item.split("x"))
                 for item in text.split(","))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--games", type=int, default=2)
    parser.add_argument("--innings", type=int, default=1,
                        help="第 i 局的局数为 1 + (i + innings - 1) % 3")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--sizes", default="46x19,80x30")
    args = parser.parse_args(argv)

    report = Report()
    sizes = _parse_sizes(args.sizes)
    for index in range(args.games):
        innings = 1 + (index + args.innings - 1) % 3
        check_match(args.seed + index, innings, sizes, report)
    print(f"模拟 {report.games} 局，检查 {report.frames} 帧")
    if report.ok:
        print("画面不变量全部满足。")
        return 0
    for code, count in report.counts.most_common():
        sample = report.samples[code]
        print(f"  {code}: {count} 次（例：种子 {sample.seed} 帧 {sample.frame} "
              f"{sample.detail}）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

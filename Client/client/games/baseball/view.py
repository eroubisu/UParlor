"""服务端下发的棋盘数据（room_update）→ 带类型的视图对象。

服务端每次都发全字段，这里严格按字段取值：缺字段说明两边协议对不上，应当立刻报错，
而不是悄悄补一个默认值把问题藏起来。渲染器与处理器只读这里的对象，不再碰字典。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# 投打动画的挥棒段（服务端 room.delivery 的 stage 值）：球已经在本垒
STAGE_SWING = 'swing'

SIDE_BATTING = 'batting'
SIDE_FIELDING = 'fielding'


@dataclass(frozen=True)
class Runner:
    """一名正在跑垒的人：`base` 是他刚离开的垒，`to` 是目标垒，进度按拍给。"""

    base: int
    to: int
    progress: int
    need: int
    settled: bool
    out: bool
    scored: bool

    @classmethod
    def parse(cls, data: dict) -> Runner:
        return cls(data['from'], data['to'], data['progress'], data['need'],
                   data['settled'], data['out'], data['scored'])

    @property
    def key(self) -> str:
        """跑者在哪条垒线上：起点垒>终点垒（同一段线上只可能有一个跑者）。"""
        return f'{self.base}>{self.to}'

    @property
    def ratio(self) -> float:
        """这条线跑了多少：0 = 起点，1 = 终点。"""
        return min(1.0, self.progress / self.need)

    @property
    def lead_ratio(self) -> float:
        """下一拍结束时跑到哪：动画朝它滑，人才不会比服务端的时钟慢一拍。"""
        if not self.running:
            return self.ratio
        return min(1.0, (self.progress + 1) / self.need)

    @property
    def running(self) -> bool:
        return not (self.settled or self.out or self.scored)


@dataclass(frozen=True)
class Fielder:
    """野手此刻的样子：位置、朝哪跑、跑多快（格/秒），以及起跳后还剩多久（秒）。

    服务端按时间匀速推算他的位置，客户端拿到这几个数就能自己接着滑——
    不用等服务端一格一格地告诉。
    """

    pos: float
    heading: int          # -1 向左 / 0 站住 / 1 向右
    speed: float
    goal: float | None    # 朝它跑到了就停（捡球时的球位、机器野手瞄准的落点）
    air: float            # 还要在空中多久
    lock: float           # 还要多久才能再跑、再跳（含空中）

    @classmethod
    def parse(cls, data: dict) -> Fielder:
        return cls(data['pos'], data['heading'], data['speed'], data['goal'],
                   data['air'], data['lock'])

    def destination(self, cells: int) -> float:
        """按现在的方向一直跑，会停在哪一格：球位 / 瞄准的格位，或者边线。"""
        if self.heading == 0:
            return self.pos
        edge = float(cells) if self.heading > 0 else 1.0
        if self.goal is None or (self.goal - self.pos) * self.heading < 0:
            return edge                  # 没有要停的格位，或者在背着它跑
        return (min(edge, self.goal) if self.heading > 0
                else max(edge, self.goal))


@dataclass(frozen=True)
class Flight:
    """飞行中：球在 `ball` 格；落点是 `span` 这一段范围，到下一拍会收窄成 `span_next`。"""

    ball: int
    span: tuple[float, float]
    span_next: tuple[float, float]
    estimate_label: str
    homerun: bool
    done: bool
    fielder: Fielder

    @classmethod
    def parse(cls, data: dict) -> Flight:
        return cls(data['ball'], tuple(data['span']),
                   tuple(data['span_next']), data['estimate_label'],
                   data['homerun'], data['done'],
                   Fielder.parse(data['fielder']))


@dataclass(frozen=True)
class ThrowOption:
    base: str
    distance: float

    @classmethod
    def parse(cls, data: dict) -> ThrowOption:
        return cls(data['base'], data['distance'])


@dataclass(frozen=True)
class Ground:
    """捡球阶段：球在外野线上的 `ball` 格（转传时球在某个垒上，`ball` 为 0、没有野手在跑）。"""

    ball: int
    ball_label: str
    at_ball: bool
    base: str
    options: tuple[ThrowOption, ...]
    fielder: Fielder | None

    @classmethod
    def parse(cls, data: dict) -> Ground:
        return cls(data['ball'], data['ball_label'], data['at_ball'],
                   data['base'],
                   tuple(ThrowOption.parse(item) for item in data['options']),
                   _optional(Fielder.parse, data['fielder']))


@dataclass(frozen=True)
class Throw:
    base: str
    distance: float
    left: int
    ticks: int
    options: tuple[ThrowOption, ...]

    @classmethod
    def parse(cls, data: dict) -> Throw:
        return cls(data['base'], data['distance'], data['left'], data['ticks'],
                   tuple(ThrowOption.parse(item) for item in data['options']))

    @property
    def done(self) -> int:
        """已经飞过的拍数。"""
        return self.ticks - self.left


@dataclass(frozen=True)
class Delivery:
    stage: str
    frame: int
    frames: int
    swung: bool

    @classmethod
    def parse(cls, data: dict) -> Delivery:
        return cls(data['stage'], data['frame'], data['frames'],
                   data['swung'])


@dataclass(frozen=True)
class Record:
    """侦察页上的一球。"""

    batter: str
    type_label: str
    band_label: str
    effort_label: str
    batter_swing_label: str
    result_label: str

    @classmethod
    def parse(cls, data: dict) -> Record:
        return cls(data['batter'], data['type_label'], data['band_label'],
                   data['effort_label'], data['batter_swing_label'],
                   data['result_label'])


@dataclass(frozen=True)
class Attributes:
    """我方三套属性：投手 / 打者 / 野手（名字 → 数值）。"""

    pitcher: dict
    batter: dict
    fielder: dict


def _optional(parser, data: dict | None):
    return None if data is None else parser(data)


@dataclass(frozen=True)
class Board:
    """一次 room_update（playing / finished）的完整视图。"""

    innings: int
    total_innings: int
    half: str
    tick_ms: int
    run_order: str
    outs: int
    bases: tuple[int, ...]
    balls: int
    strikes: int
    score: dict
    away: str
    home: str
    batting: str
    fielding: str
    phase: str
    side: str
    shift: str
    shift_label: str
    field_start: int
    cells: int
    stamina: int
    winner: str
    flight: Flight | None
    runners: tuple[Runner, ...]
    ready_fielding: bool
    ready_batting: bool
    countdown: int
    armed: bool
    base_distances: dict
    verdict: str
    last_ball: str
    delivery: Delivery | None
    ground: Ground | None
    throw: Throw | None
    labels: dict
    timing_cuts: tuple[float, ...]
    history: tuple[Record, ...]
    attributes: Attributes
    line_score: dict[str, tuple[int | None, ...]]
    finished: bool

    @classmethod
    def parse(cls, data: dict) -> Board:
        ready = data['ready']
        attributes = data['attributes']
        return cls(
            innings=data['innings'], total_innings=data['total_innings'],
            half=data['half'], tick_ms=data['tick_ms'],
            run_order=data['run_order'], outs=data['outs'],
            bases=tuple(data['bases']), balls=data['balls'],
            strikes=data['strikes'], score=data['score'], away=data['away'],
            home=data['home'], batting=data['batting'],
            fielding=data['fielding'], phase=data['phase'],
            side=data['viewer_side'], shift=data['shift'],
            shift_label=data['shift_label'], field_start=data['field_start'],
            cells=data['cells'], stamina=data['stamina'],
            winner=data['winner'],
            flight=_optional(Flight.parse, data['flight']),
            runners=tuple(Runner.parse(item) for item in data['runners']),
            ready_fielding=ready['fielding'], ready_batting=ready['batting'],
            countdown=data['countdown'], armed=data['armed'],
            base_distances=data['base_distances'], verdict=data['verdict'],
            last_ball=data['last_ball'],
            delivery=_optional(Delivery.parse, data['delivery']),
            ground=_optional(Ground.parse, data['ground']),
            throw=_optional(Throw.parse, data['throw']),
            labels=data['labels'],
            timing_cuts=tuple(data['timing_cuts']),
            history=tuple(Record.parse(item) for item in data['history']),
            attributes=Attributes(attributes['pitcher'], attributes['batter'],
                                  attributes['fielder']),
            line_score={side: tuple(runs)
                        for side, runs in data['line_score'].items()},
            finished=data['room_state'] == 'finished',
        )

    def with_swing(self) -> Board:
        """自己刚按下击球、服务端的回执还在路上：先按「已挥棒」画。"""
        return replace(self, delivery=replace(self.delivery, swung=True))

    def with_arrival(self) -> Board:
        """画面上的野手已经跑到了球位、服务端的回执还在路上：先按「已到球位」画。"""
        return replace(self, ground=replace(self.ground, at_ball=True))

    @property
    def fielder(self) -> Fielder | None:
        """场上正在追球 / 捡球的野手（球还没打出去、或转传时没有）。"""
        if self.flight:
            return self.flight.fielder
        return self.ground.fielder if self.ground else None

    @property
    def fielding_side(self) -> bool:
        return self.side == SIDE_FIELDING

    @property
    def batting_side(self) -> bool:
        return self.side == SIDE_BATTING

    def values(self, key: str) -> tuple[tuple[str, str], ...]:
        """某个设置项的可选取值：[(取值, 文案), …]。"""
        return tuple(tuple(pair) for pair in self.labels[key])

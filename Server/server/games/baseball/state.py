"""棒球对局里每个阶段自己的状态对象。

房间（room.py）只负责阶段切换与比分；每个阶段的数据、它自己的那一小段推进逻辑
和下发给客户端的样子（`view()`）都住在这里，房间里不再有无名字典。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import rules


@dataclass(frozen=True)
class Tick:
    """计时器下一拍的种类与时长；两拍相等＝同一条计时链还在继续。"""

    kind: str          # countdown / delivery / flight / ground / throw
    ms: int


# ── 一球的投打 ──

@dataclass
class Exchange:
    """一球的投打交锋：双方交的牌，以及动画走完才揭晓的结果。"""

    pitch: rules.PitchCall
    swing: rules.SwingCall
    result: rules.PitchResult | None = None


@dataclass
class Delivery:
    """投球段（球从投手飞向本垒）→ 挥棒段（球到本垒）的动画进度。"""

    stage: str = rules.DELIVERY_PITCH
    frame: int = 0
    frames: int = rules.PITCH_ANIM_FRAMES
    swung: bool = False
    tick_at: float = 0.0       # 当前这一帧是什么时候开始的（房间的时钟）：按键时据此折算帧内进度

    def advance(self) -> bool:
        """走一帧；整段走完（该揭晓了）返回 True。"""
        self.frame += 1
        if self.frame < self.frames:
            return False
        if self.stage == rules.DELIVERY_PITCH:
            self.stage = rules.DELIVERY_SWING
            self.frame = 0
            self.frames = rules.SWING_ANIM_FRAMES
            return False
        return True

    def view(self) -> dict:
        return {'stage': self.stage, 'frame': self.frame,
                'frames': self.frames, 'swung': self.swung}


@dataclass
class PitchRecord:
    """侦察板上的一球：揭晓那一刻才记，动画期间谁都看不到。"""

    pitch: rules.PitchCall
    swing: rules.SwingCall
    result: rules.PitchResult
    batter: str

    def view(self) -> dict:
        return {
            'batter': self.batter,
            'type_label': rules.PITCH_TYPE_SHORT[self.pitch.pitch_type],
            'band_label': rules.BAND_LABELS[self.pitch.band],
            'effort_label': rules.EFFORT_LABELS[self.pitch.effort],
            'batter_swing_label': rules.SWING_SHORT[self.swing.swing],
            'result_label': rules.RESULT_LABELS[self.result.kind],
        }


# ── 跑者 ──

@dataclass
class Runner:
    """一名跑者在这次击球里的跑垒进度。

    `at` 是他刚离开（或正站着）的垒，`to` 是他要去的垒；`progress / need` 是这一段
    跑了多少拍。跑到垒时接着跑还是站住，由进攻方此刻的指令决定（前进 / 停止 / 撤回）；
    `back` 是正在往回跑；`bonus` 是球滚开时白送的额外垒数（指令之外）。
    """

    name: str
    origin: int
    at: int
    to: int
    need: int
    settled: bool
    progress: int = 0
    bonus: int = 0
    out: bool = False
    scored: bool = False
    batter: bool = False
    forced: bool = False       # 击球那一刻被挤着必须往前跑（含打者）
    back: bool = False
    how: str = ''              # 出局方式（接杀 / 封杀 / 触杀）

    @classmethod
    def start(cls, name: str, base: int, need: int, forced: bool,
              batter: bool = False) -> Runner:
        """forced＝被挤着必须往前跑，否则先站在原垒等指令。"""
        return cls(name=name, origin=base, at=base,
                   to=base + 1 if forced else base, need=need,
                   settled=not forced, batter=batter, forced=forced)

    @property
    def live(self) -> bool:
        return not self.out and not self.scored

    @property
    def pinned(self) -> bool:
        """被挤着必须往前跑的人，第一段跑完之前不能回头。"""
        return self.forced and self.at == self.origin

    def step(self, go: bool) -> None:
        """这一拍往前跑一步；跑完一段就站稳、得分，或在「前进」时接着跑。"""
        if self.settled or self.out:
            return
        self.progress += 1
        if self.progress < self.need:
            return
        returning = self.back
        self.at = self.to
        self.progress = 0
        self.back = False
        if self.at >= rules.HOME:
            self.scored = True
            self.settled = True
        elif returning:
            self.settled = True                  # 跑回了刚离开的垒
        elif go or self.bonus > 0:
            self.bonus = max(0, self.bonus - 1)
            self.to = self.at + 1                # 接着往下一个垒跑
        else:
            self.settled = True

    def go(self) -> None:
        """前进：站着的人起跑，往回跑的人调头；已经在往前跑的人到垒时接着跑（见 `step`）。"""
        if self.back:
            self._reverse()
        elif self.settled and self.at < rules.HOME:
            self.settled = False
            self.progress = 0
            self.to = self.at + 1

    def halt(self) -> None:
        """停止：站在最近的垒上。还没真正离开垒（刚起跑、或刚到垒准备接着跑）的人就留在原地；
        已经在半路上的人跑到下一个垒再站住（见 `step`）。被挤着必须跑的第一段不能留。"""
        if self.settled or self.out or self.back or self.pinned:
            return
        if self.progress == 0:
            self.to = self.at
            self.bonus = 0
            self.settled = True

    def retreat(self) -> None:
        """撤回：还在半路上、又不是被挤着必须跑的人调头跑回刚离开的垒。

        已经跑过多久，回来就要多久；还没离开那个垒（刚起跑）就留在原地。
        """
        if self.settled or self.out or self.back or self.pinned:
            return
        self.bonus = 0
        if self.progress == 0:
            self.to = self.at
            self.settled = True
            return
        self._reverse()

    def _reverse(self) -> None:
        self.at, self.to = self.to, self.at
        self.progress = self.need - self.progress
        self.back = not self.back

    def push(self) -> None:
        """球滚开 / 盗垒起跑：站着的人起跑，正在跑的人跑完这一段再多跑一个垒。"""
        if self.settled:
            self.go()
        else:
            self.bonus += 1

    def return_to_origin(self) -> None:
        self.at = self.to = self.origin
        self.progress = 0
        self.bonus = 0
        self.back = False
        self.settled = True

    def view(self) -> dict:
        return {'from': self.at, 'to': self.to, 'progress': self.progress,
                'need': self.need, 'settled': self.settled, 'out': self.out,
                'scored': self.scored}


# ── 击出之后 ──

@dataclass
class Fielder:
    """外野手：按真实时间匀速奔跑（不是一格一格地跳）；起跳后要缓一缓才能再跑再跳。

    位置只在被问到或被操作时才按时钟推算，服务端不需要为他开计时器。
    `goal` 是要停下的格位（捡球时的球位、机器野手瞄准的落点）：朝它跑到了就停，
    背着它跑不受限制。
    """

    pos: float
    speed: float               # 每秒跑几格
    at: float                  # `pos` 是房间时钟哪个时刻的位置
    heading: int = 0           # -1 向左 / 0 站住 / 1 向右
    goal: float | None = None
    jumped_at: float | None = None

    def _free_at(self) -> float:
        """起跳之后哪个时刻起又能跑、又能跳。"""
        if self.jumped_at is None:
            return self.at
        return (self.jumped_at + rules.FIELDER_AIR_SECONDS
                + rules.FIELDER_REST_SECONDS)

    def position(self, now: float) -> float:
        run = max(0.0, now - max(self.at, self._free_at()))
        pos = self.pos + self.heading * self.speed * run
        pos = max(1.0, min(float(rules.FIELD_CELLS), pos))
        if self.goal is not None:
            if self.heading > 0 and self.pos <= self.goal:
                pos = min(pos, self.goal)
            elif self.heading < 0 and self.pos >= self.goal:
                pos = max(pos, self.goal)
        return pos

    def _commit(self, now: float) -> None:
        self.pos = self.position(now)
        self.at = now

    def airborne(self, now: float) -> bool:
        return (self.jumped_at is not None
                and self.jumped_at <= now <= self.jumped_at
                + rules.FIELDER_AIR_SECONDS)

    def steer(self, heading: int, now: float) -> bool:
        """改跑动方向（0＝站住）；方向没变返回 False。"""
        if heading == self.heading:
            return False
        self._commit(now)
        self.heading = heading
        return True

    def run_to(self, target: float, now: float) -> None:
        """机器野手：朝 target 跑，到了就停。"""
        self._commit(now)
        self.goal = target
        self.heading = (target > self.pos) - (target < self.pos)

    def retune(self, speed: float, goal: float | None, now: float) -> None:
        """换一个阶段：从当前位置接着跑，换速度和停下的格位。"""
        self._commit(now)
        self.speed = speed
        self.goal = goal

    def place(self, pos: float, now: float) -> None:
        """被放到某一格（滚地球滚到了他脚下）：站住。"""
        self.pos = pos
        self.at = now
        self.heading = 0

    def jump(self, now: float) -> bool:
        """起跳；还在上一跳的空中或缓冲里就跳不了。"""
        if now < self._free_at():
            return False
        self._commit(now)
        self.jumped_at = now
        return True

    def view(self, now: float) -> dict:
        air = lock = 0.0
        if self.jumped_at is not None:
            air = max(0.0, self.jumped_at + rules.FIELDER_AIR_SECONDS - now)
            lock = max(0.0, self._free_at() - now)
        return {
            'pos': round(self.position(now), 3), 'heading': self.heading,
            'speed': round(self.speed, 4), 'goal': self.goal,
            'air': round(air, 3), 'lock': round(lock, 3),
        }


@dataclass
class Flight:
    """击出的球在外野线上飞：球逐格推进，野手匀速跑位，球到的那一刻判接球。"""

    hit: rules.HitBall
    fielder: Fielder
    ball: int = rules.FIELD_START
    tick: int = 0
    done: bool = False

    def advance(self) -> bool:
        """球飞一拍；抵达落点（该判定接球了）返回 True。"""
        self.tick += 1
        self.ball = rules.ball_position(self.hit, self.tick)
        return self.tick >= self.hit.ticks

    def estimate(self) -> float:
        """这一拍玩家看到的落点范围正中。"""
        return self.hit.estimate_at(self.tick)

    def view(self, now: float) -> dict:
        low, high = self.hit.span_at(self.tick)
        next_low, next_high = self.hit.span_at(self.tick + 1)
        return {
            'ball': self.ball,
            'span': [round(low, 3), round(high, 3)],
            'span_next': [round(next_low, 3), round(next_high, 3)],
            'estimate_label': rules.field_label(self.estimate()),
            'homerun': self.hit.homerun, 'done': self.done,
            'fielder': self.fielder.view(now),
        }


@dataclass
class ThrowOption:
    """传球菜单里的一项：目标垒、传球距离、需要几拍。"""

    base: str
    distance: float
    ticks: int

    def view(self) -> dict:
        return {'base': self.base, 'distance': self.distance}


@dataclass
class Pickup:
    """球落地后野手跑去捡球；跑到球位（到了自动停住）才能传。"""

    hit: rules.HitBall
    fielder: Fielder
    error: bool
    tick: int = 0

    @property
    def ball(self) -> int:
        return self.hit.landing

    def at_ball(self, now: float) -> bool:
        return self.fielder.position(now) == self.ball

    def distance_to(self, base: str) -> float:
        return rules.throw_distance(self.ball, self.hit.kind, base)

    def step(self) -> bool:
        """过一拍；捡球超时（守方控制球）返回 True。"""
        self.tick += 1
        return self.tick >= rules.GROUND_MAX_TICKS

    def view(self, options: list[ThrowOption], now: float) -> dict:
        return {
            'ball': self.ball, 'ball_label': rules.field_label(self.ball),
            'at_ball': self.at_ball(now), 'base': '',
            'options': [option.view() for option in options],
            'fielder': self.fielder.view(now),
        }


@dataclass
class Relay:
    """球已经传到某个垒上，守方可以转传（连续双杀）；球在垒上不用再跑。"""

    base: str

    ball = 0
    fielder = None

    def at_ball(self, now: float) -> bool:
        return True

    def distance_to(self, base: str) -> float:
        return rules.base_distance(self.base, base)

    def step(self) -> bool:
        return False                     # 决定阶段：不会超时

    def view(self, options: list[ThrowOption], now: float) -> dict:
        return {
            'ball': self.ball, 'ball_label': self.base,
            'at_ball': True, 'base': self.base,
            'options': [option.view() for option in options],
            'fielder': None,
        }


@dataclass
class Throw:
    """传球途中：球按拍数飞向目标垒，到垒那一拍才判封杀 / 触杀 / 安全。"""

    base: str
    distance: float
    ticks: int
    left: int
    options: list[ThrowOption] = field(default_factory=list)

    def view(self) -> dict:
        return {'base': self.base, 'distance': self.distance,
                'left': self.left, 'ticks': self.ticks,
                'options': [option.view() for option in self.options]}


@dataclass
class Tag:
    """高飞被接杀后的触垒窗口：球接住的位置与球型，决定守方传杀的距离。"""

    cell: float
    kind: str

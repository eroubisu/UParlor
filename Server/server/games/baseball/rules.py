"""棒球规则内核 — 纯函数，不碰房间、网络和定时器。

设计要点（与 docs/design/baseball.md 一致）：
- 投球是「球种 × 区域带 × 力度」的取舍，力度换来球速却牺牲控球与体力；
- 打击靠「读投手」：预判球种 + 挥棒类型 + 时机档，命中率由推理质量决定；
- 击球后球进入一条**外野线**，逐格推进，野手自己跑、自己选接球动作；
- 漏接取决于野手属性、跑位差与动作是否匹配球型。
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from math import ceil, hypot

# ── 选项与文案 ──

PITCH_TYPES = ('four_seam', 'cutter', 'slider', 'changeup', 'splitter')
PITCH_TYPE_LABELS = {
    'four_seam': '四缝线速球 Four-Seam Fastball',
    'cutter': '卡特球 Cutter',
    'slider': '滑球 Slider',
    'changeup': '变速球 Changeup',
    'splitter': '指叉球 Splitter',
}


@dataclass(frozen=True)
class PitchProfile:
    """一种球的性格（用户 2026-10-15 定：5 个球种，每个都要真的不一样）。

    - `velocity`：加到投手球速上——越快越压制打者（但成本看 `stamina`）；
    - `break_amount`：变化量权重，1.0 = 老版「变化球」那一档；
    - `control`：加到控球上，正数更少失投，负数更容易跑偏；
    - `stamina`：这一球花几倍体力（0.6 = 省，1.4 = 很费）；
    - `timing`：打者要按的那一档时机（提前 / 正常 / 延后）。
    """

    velocity: int
    break_amount: float
    control: int
    stamina: float
    timing: str


PITCH_PROFILES = {
    # 最快、零变化：最压打者，也最吃体力
    'four_seam': PitchProfile(2, 0.0, 0, 1.25, 'early'),
    # 快球加一点横向变化：控球最稳、体力不额外花，但速度压制只有一半
    'cutter': PitchProfile(1, 0.5, 1, 1.0, 'early'),
    # 标准变化球：中等速度、变化大
    'slider': PitchProfile(0, 1.0, 0, 1.0, 'normal'),
    # 慢速、省体力、诱打者早挥，代价是球速压低、被打到更扎实
    'changeup': PitchProfile(-2, 0.5, 0, 0.6, 'late'),
    # 变化最大，但控球差（更容易失投）、体力最费
    'splitter': PitchProfile(0, 1.5, -1, 1.4, 'late'),
}

# 面板（侦察页那一列）用的短名：菜单带英文（英文是权威写法），面板只放中文——
# 30 多列的面板塞不下 `四缝线速球 Four-Seam Fastball`，会被裁掉尾巴。
PITCH_TYPE_SHORT = {
    'four_seam': '四缝线速球', 'cutter': '卡特球', 'slider': '滑球',
    'changeup': '变速球', 'splitter': '指叉球',
}

BANDS = ('inside', 'edge', 'outside')
BAND_LABELS = {'inside': '好球带内', 'edge': '好球带边缘', 'outside': '坏球区'}

EFFORTS = ('normal', 'full')
EFFORT_LABELS = {'normal': '标准', 'full': '全力'}

# 投手盯不盯跑者：盯住能压低盗垒成功率，代价是分心（打者更好打）
HOLDS = ('no', 'yes')
# 盯防是个真取舍（不是"永远更好"）：牵制跑者→盗垒成功率减半，但投手分心、打者接触率 +8%。
# 两个取值都用棒球里的正式说法（用户 2026-10-16：不要口语化），不写数字、不解释机制。
HOLD_LABELS = {'no': '不牵制', 'yes': '牵制跑者'}

# 挥棒三项（用户 2026-10-15 定：不要「等球」选项，取 标准 / 大力 / 滚地球 三种）。
# `take` 不是选项，但还在：**不按击球键**就是放过去，判定与播报都走它。
SWINGS = ('standard', 'power', 'ground')
SWING_LABELS = {
    'standard': '标准挥击 Standard Swing',
    'power': '大力挥击 Power Swing',
    'ground': '滚地球 Ground Ball',
    'take': '未挥棒 Take',
}
# 面板（侦察页那一列）用的短名：菜单带英文，面板只放中文（列宽只有 30 出头）
SWING_SHORT = {
    'standard': '标准挥击', 'power': '大力挥击', 'ground': '滚地球',
    'take': '未挥棒',
}

TIMINGS = ('early', 'normal', 'late')
TIMING_LABELS = {'early': '提前', 'normal': '正常', 'late': '延后'}

SHIFTS = ('standard', 'left', 'right', 'infield', 'deep')
SHIFT_LABELS = {
    'standard': '标准站位', 'left': '偏左外野', 'right': '偏右外野',
    'infield': '内野前压', 'deep': '外野退守',
}

# 一球的结果（侦察板展示用）
RESULT_LABELS = {
    'strike': '好球', 'ball': '坏球', 'swing_miss': '挥空',
    'foul': '界外', 'contact': '击中',
}

# 外野线：坐标 1 = 左外野边线，12 = 右外野边线，6 为中线
FIELD_CELLS = 12
FIELD_MID = 6
FIELD_START = 1     # 球从 1 号位（左外野边线）起飞
PHASE_SLOWDOWN = 2  # 投打以外的动态阶段统一慢放倍率

# 球型 → 落点范围、每格飞行时长、最合适的接球动作。
# 一格一拍；球型决定基础格长，非投打阶段共用 PHASE_SLOWDOWN。
BALL_KINDS = {
    'ground': {'label': '滚地球', 'cells': (2, 8),
               'cell_ms': 880 * PHASE_SLOWDOWN},
    'line': {'label': '平飞球', 'cells': (4, 11),
             'cell_ms': 960 * PHASE_SLOWDOWN},
    'fly': {'label': '高飞球', 'cells': (6, 12),
            'cell_ms': 1120 * PHASE_SLOWDOWN},
}
FLIGHT_MOVE_CELLS = 3.0       # 一段飞行里野手能跑的总格数（速度 ≥7 翻倍）；野手匀速跑完整段

# 起跳（回车）：空中那一段把接球范围拉大、但手感更糙；落地后缓一缓才能再跑再跳
FIELDER_AIR_SECONDS = 1.0     # 起跳后在空中的时间：球正好在这段里到达才算跳到了
FIELDER_REST_SECONDS = 1.0    # 落地后的缓冲：不能跑也不能再跳
LUNGE_REACH_BONUS = 2         # 在空中时多覆盖的格数
LUNGE_MISS = 0.20             # 在空中接球额外增加的脱手概率

# 落点范围：球一击出就是一段范围（含真落点，但真落点不在正中），随球飞近一路收窄，
# 到落点收成一点。打得越结实，刚出手时的范围越宽（以前是预测落点带 ±1~2 格的误差）
SPAN_HALF_MIN = 1.2           # 最软的击球：刚出手时范围的半宽（格）
SPAN_HALF_MAX = 3.0           # 最结实的击球
SPAN_OFFSET = (0.25, 0.85)    # 真落点离范围正中的距离占半宽的比例：不正中、也不贴边

# 接球判定：站得再正也不是稳接——脱手概率随"超出覆盖的格数"和"击球质量"上升
FIELD_MISS_BASE = 0.05        # 落点差在覆盖范围内时的脱手概率
FIELD_MISS_PER_GAP = 0.30     # 每超出覆盖 1 格

# 布阵：外野线起始格位 + 对球型的覆盖加成
_SHIFT_START = {
    'standard': FIELD_MID, 'left': 3, 'right': 9,
    'infield': FIELD_MID, 'deep': FIELD_MID,
}
_SHIFT_BONUS = {
    'infield': {'ground': 1}, 'deep': {'fly': 1, 'line': 1},
}

BASE_COVERAGE = 1             # 不起跳时左右各能够到几格：范围小、手感稳

# 好球带判定：进垒点 → 是否好球
STRIKE_ZONES = ('heart', 'edge')

# 击球质量：读准球种/时机 + 打者属性抬高，投手属性压低；
# 质量越高球越难接（每点 +0.5% 脱手），到 HOMERUN_QUALITY 以上才可能飞出墙外
QUALITY_MISS_PER_POINT = 0.005
HOMERUN_QUALITY = 78
HOMERUN_CHANCE_STEP = 0.02
HOMERUN_CHANCE_CAP = 0.5

# 挥棒判定（2026-10-15 用户要求：击进场内要比现实更多，球多留在场上更好玩）：
# 基础接触率 0.80（判对球种 + 时机时会被上限截到 0.95），没打中时挥空:界外 = 55:45。
# 实测 40 局机器人对局：挥空 14%、界外 19%、击进场内 67%（真实棒球是 20% / 18% / 60%）。
CONTACT_BASE = 0.80
CONTACT_PER_ATTRIBUTE = 0.035
CONTACT_TIMING_BONUS = 0.18
CONTACT_TIMING_GAP_PENALTY = 0.12
CONTACT_GUESS_BONUS = 0.12
CONTACT_GUESS_PENALTY = 0.08
CONTACT_MIN = 0.05
CONTACT_MAX = 0.95
WHIFF_SHARE = 0.55              # 没打中时是挥空的比例（其余算界外）
# 得失分一律按比例算（乘法），不能相加：读得准的人接触率本来就顶到 CONTACT_MAX，
# 相加的惩罚会被上限整口吃掉，强挥/全力/变化球在他面前全部变成免费选项。
POWER_CONTACT_COST = 0.25       # 强挥的接触代价（力量属性每点减 1%）
POWER_QUALITY_BONUS = 2         # 强挥的质量加成（力量属性另有每点 +4）
GROUND_CONTACT_BONUS = 0.05     # 滚地球打法：收着挥、以碰到球为先
GROUND_QUALITY_CAP = 44         # 滚地球的质量上限（球一定压在地上，没有长打）
GROUND_WILD_STEP = 0.04         # 球种控球修正：每一点（正数更稳、负数更容易跑偏）
CHASE_CONTACT_COST = 0.13       # 追打坏球区的接触代价
CHASE_POWER_EXTRA = 0.08        # 强挥追打坏球区，代价更大
CONTACT_HEART_BONUS = 0.06      # 好球带中心被结实击中
FULL_EFFORT_CONTACT_COST = 0.05    # 全力投球对接触率的代价（球速每点再 +1.5%）
CONTACT_VELOCITY_STEP = 0.015
CONTACT_BREAKING_STEP = 0.02       # 变化球：投手变化每点
POWER_ATTRIBUTE_RELIEF = 0.01      # 打者力量每点能让强挥的代价轻 1%
CONTACT_COST_FLOOR = 0.5           # 乘法代价最多扣掉一半，别扣到打不着球
# 选球（eye）＝1 坏球区收棒：挥棒指令下、球在坏球区时按选球概率收住，
# 这一球改按好坏球判（多半变坏球 → 保送变多、三振变少）；
#           ＝2 猜错补救：猜错球种时按选球减轻接触率与质量的惩罚。
CHECK_SWING_BASE = 0.25         # 选球 5 的收棒率
CHECK_SWING_STEP = 0.06         # 每点选球
EYE_RECOVER_CONTACT = 0.012     # 猜错时每点选球补回的接触率
EYE_RECOVER_QUALITY = 2         # 猜错时每点选球补回的质量


# ── 球员属性 ──

@dataclass
class PitcherAttributes:
    control: int = 5     # 控球：减少力度造成的失投
    velocity: int = 5    # 球速：压低打者命中
    breaking: int = 5    # 变化：变化球威力


@dataclass
class BatterAttributes:
    power: int = 5       # 力量：强挥的收益与风险
    contact: int = 5     # 接触：挥棒命中与容错
    eye: int = 5         # 选球：收棒与猜错补救


@dataclass
class FielderAttributes:
    speed: int = 5       # 速度：每 tick 移动能力
    fielding: int = 5    # 守备：接球成功率
    arm: int = 5         # 臂力：传杀成功


@dataclass
class PlayerAttributes:
    """一名球员在对局里的三套属性（投 / 打 / 守）。"""

    pitcher: PitcherAttributes
    batter: BatterAttributes
    fielder: FielderAttributes

    def view(self) -> dict:
        return {'pitcher': asdict(self.pitcher), 'batter': asdict(self.batter),
                'fielder': asdict(self.fielder)}


def roll_attributes(rng: random.Random) -> PlayerAttributes:
    """生成一套 3-8 的球员属性（对局开始时随机，只有本人看得到）。"""
    def one() -> int:
        return max(3, min(8, 5 + rng.choice((-1, 0, 0, 1))
                          + rng.choice((0, 0, 1))))

    return PlayerAttributes(
        PitcherAttributes(one(), one(), one()),
        BatterAttributes(one(), one(), one()),
        FielderAttributes(one(), one(), one()),
    )


# ── 决策与结果 ──

@dataclass
class PitchCall:
    pitch_type: str
    band: str
    effort: str
    hold: str = 'no'


@dataclass
class SwingCall:
    guess: str
    swing: str
    timing: str = 'normal'
    steal: str = 'hold'      # 盗垒范围（RUN_SCOPES），随这一球一起交牌


@dataclass
class HitBall:
    kind: str = 'line'
    landing: int = FIELD_MID     # 真实落点格
    shown: float = FIELD_MID     # 刚出手时落点范围的正中（偏离真落点，不泄露它）
    spread: float = 1.0          # 刚出手时落点范围的半宽（含真落点）
    ticks: int = 5
    tick_ms: int = 130
    homerun: bool = False
    quality: int = 50

    def _ratio(self, tick: int) -> float:
        return max(0.0, min(1.0, tick / max(1, self.ticks)))

    def estimate_at(self, tick: int) -> float:
        """第 tick 拍时落点范围的正中：从 `shown` 一路挪向真落点。"""
        return self.shown + (self.landing - self.shown) * self._ratio(tick)

    def span_at(self, tick: int) -> tuple[float, float]:
        """第 tick 拍时玩家看到的落点范围：刚出手最宽，一路收窄，球到落点时收成一点。"""
        center = self.estimate_at(tick)
        half = self.spread * (1 - self._ratio(tick))
        return center - half, center + half


@dataclass
class PitchResult:
    """一次投球的结果。"""

    kind: str                    # ball / strike / swing_miss / foul / contact
    message: str
    zone: str                    # 实际进垒点
    hit: HitBall | None = None


@dataclass
class PlayOutcome:
    """保送等强制推进之后的垒上局面。"""

    bases: list[int]             # 结束后占垒的垒包
    runs: int                    # 本次得分


# ── 投打判定 ──

def _zone_from_band(band: str, effort: str, control: int,
                    rng: random.Random, wild_shift: float = 0.0) -> str:
    """按瞄准带、力度与控球算出真实进垒点。

    `wild_shift` 是球种自带的跑偏量（指叉球那种难控的球更多失投）。
    """
    heart, edge, outside = {
        'inside': (0.60, 0.34, 0.06),
        'edge': (0.18, 0.60, 0.22),
        'outside': (0.03, 0.25, 0.72),
    }[band]
    if effort == 'full':
        shift = max(0.02, 0.12 - (control - 5) * 0.02)
        heart = max(0.05, heart - shift)
        outside += shift
    if wild_shift > 0:
        # 难控的球种：好球带中心被削掉，漂到边缘/坏球区
        take = min(heart - 0.05, wild_shift)
        heart -= take
        outside += take
    roll = rng.random()
    if roll < heart:
        return 'heart'
    if roll < heart + edge:
        return 'edge'
    return 'outside'


ZONE_LABELS = {'heart': '好球带中心', 'edge': '好球带边缘', 'outside': '坏球区'}


def expected_timing(pitch_type: str, effort: str) -> str:
    """该球种/力度对应的正确时机档——打者要靠推理 + 手感去对上它。"""
    base = PITCH_PROFILES[pitch_type].timing
    if effort == 'full':
        base = {'early': 'early', 'normal': 'early',
                'late': 'normal'}[base]
    return base


# 击球是实时反应（2026-10-15 用户定档）：打者交的是"预判球种 + 挥棒方式"，
# 真正的时机由**他按下击球的那一帧**决定——球来得快（直球）就得早按。
DELIVERY_PITCH = 'pitch'      # 投球段：球从投手一侧飞向本垒
DELIVERY_SWING = 'swing'      # 挥棒段：球已到本垒，打者符号按结果变
SWING_EARLY_RATIO = 0.45      # 投球段前 45% 内按下 = 提前
SWING_NORMAL_RATIO = 0.80     # 前 80% 内 = 正常，再晚 = 延后

# 击球时机由服务端校验（2026-10-17 用户定档：防作弊，同时补偿网络延迟）：
# 客户端报它插值出来的帧，服务端只把它往回认最多这么几帧——
# 2 帧 × 140ms = 280ms，盖得住正常网络延迟；报未来、报得离谱、或报的不是数字，
# 一律按服务端当前帧算（见 room.swing_now）。
HIT_LATENCY_TOLERANCE_FRAMES = 2


def swing_timing(frame: float, frames: int,
                 stage: str = DELIVERY_PITCH) -> str:
    """按下击球的那一帧落在哪一档：早按＝提前、中间＝正常、晚按＝延后。

    球已经到本垒（挥棒段）里再按就是「延后」——那是很晚的一挥（用户 2026-10-15 定）。
    """
    if stage != DELIVERY_PITCH:
        return 'late'
    ratio = max(0.0, min(1.0, frame / frames))
    if ratio < SWING_EARLY_RATIO:
        return 'early'
    if ratio < SWING_NORMAL_RATIO:
        return 'normal'
    return 'late'


def _checked_swing(eye: int, rng: random.Random) -> bool:
    """选球＝坏球区收棒能力：选球越高越可能及时收住（这一球改按好坏球判）。"""
    chance = CHECK_SWING_BASE + (eye - 5) * CHECK_SWING_STEP
    return rng.random() < max(0.0, min(0.9, chance))


def resolve_pitch(pitch: PitchCall, swing: SwingCall,
                  pitcher: PitcherAttributes, batter: BatterAttributes,
                  rng: random.Random) -> PitchResult:
    """判定一次投打。"""
    profile = PITCH_PROFILES[pitch.pitch_type]
    zone = _zone_from_band(
        pitch.band, pitch.effort, pitcher.control + profile.control, rng,
        max(0.0, -profile.control * GROUND_WILD_STEP),
    )
    is_strike = zone in STRIKE_ZONES
    call = 'strike' if is_strike else 'ball'
    verdict = '好球' if is_strike else '坏球'

    if swing.swing == 'take':
        return PitchResult(call, f'未挥棒 {verdict} {ZONE_LABELS[zone]}', zone)

    want = expected_timing(pitch.pitch_type, pitch.effort)
    timing_gap = abs(TIMINGS.index(swing.timing) - TIMINGS.index(want))
    guess_ok = swing.guess == pitch.pitch_type

    if zone == 'outside' and _checked_swing(batter.eye, rng):
        # 坏球区收棒：这一球按好坏球判（坏球 → 记一个坏球）
        return PitchResult(call, f'收棒 {verdict} {ZONE_LABELS[zone]}', zone)

    contact = _contact_rate(zone, guess_ok, timing_gap, swing, pitch,
                            batter, pitcher)

    if rng.random() > contact:
        if rng.random() < WHIFF_SHARE:
            return PitchResult('swing_miss', '挥空', zone)
        return PitchResult('foul', '界外', zone)

    hit = _make_hit_ball(zone, guess_ok, timing_gap == 0, swing, pitch,
                         batter, pitcher, rng)
    extra = ' 全垒打' if hit.homerun else ''
    return PitchResult(
        'contact',
        f'击中 {BALL_KINDS[hit.kind]["label"]}{extra} '
        f'{field_label(hit.estimate_at(0))}',
        zone, hit,
    )


def _contact_rate(zone: str, guess_ok: bool, timing_gap: int,
                  swing: SwingCall, pitch: PitchCall, batter: BatterAttributes,
                  pitcher: PitcherAttributes) -> float:
    """这一球打不打得到：收益相加、代价相乘。

    收益相加是为了让"读准球种 + 对上时机"值钱；代价必须相乘——读得准的人接触率本来就
    顶到 CONTACT_MAX，相加的代价会被上限整口吃掉（强挥的 −10% 就成了免费）。
    """
    contact = CONTACT_BASE + (batter.contact - 5) * CONTACT_PER_ATTRIBUTE
    contact += CONTACT_TIMING_BONUS if timing_gap == 0 \
        else -CONTACT_TIMING_GAP_PENALTY * timing_gap
    if guess_ok:
        contact += CONTACT_GUESS_BONUS
    else:
        contact += -CONTACT_GUESS_PENALTY + (batter.eye - 5) * EYE_RECOVER_CONTACT
    if zone == 'heart':
        contact += CONTACT_HEART_BONUS
    contact = max(CONTACT_MIN, min(CONTACT_MAX, contact))

    if swing.swing == 'power':
        contact *= max(CONTACT_COST_FLOOR, 1 - POWER_CONTACT_COST
                       + (batter.power - 5) * POWER_ATTRIBUTE_RELIEF)
    elif swing.swing == 'ground':
        contact += GROUND_CONTACT_BONUS        # 收着挥：更碰得到球
    profile = PITCH_PROFILES[pitch.pitch_type]
    if pitch.effort == 'full':
        velocity = pitcher.velocity + profile.velocity
        contact *= max(CONTACT_COST_FLOOR, 1 - FULL_EFFORT_CONTACT_COST
                       - (velocity - 5) * CONTACT_VELOCITY_STEP)
    if profile.break_amount:
        contact *= max(CONTACT_COST_FLOOR, 1 - (pitcher.breaking - 5)
                       * CONTACT_BREAKING_STEP * profile.break_amount)
    if zone == 'outside':
        cost = CHASE_CONTACT_COST + (CHASE_POWER_EXTRA
                                     if swing.swing == 'power' else 0.0)
        contact *= 1 - cost
    if pitch.hold == 'yes':
        contact *= 1 + HOLD_CONTACT_GIFT
    return max(CONTACT_MIN, min(1.0, contact))


def _make_hit_ball(zone: str, guess_ok: bool, timing_ok: bool,
                   swing: SwingCall, pitch: PitchCall, batter: BatterAttributes,
                   pitcher: PitcherAttributes, rng: random.Random) -> HitBall:
    """由打击质量推出球型、落点与飞行参数。

    质量靠"读准球种 + 对上时机 + 打者属性"堆起来，投手的球速/变化会压低它；
    没读准就明显下降。质量越高，飞得越远、也越难被接住。
    """
    quality = 42
    quality += (batter.contact - 5) * 4           # 接触：打得到球的底子
    quality += 14 if guess_ok else (-8 + (batter.eye - 5)
                                    * EYE_RECOVER_QUALITY)   # 读准 / 选球补救
    quality += 14 if timing_ok else -8            # 时机对上
    quality += 7 if zone == 'heart' else (-7 if zone == 'outside' else 0)
    quality += 6 if pitch.effort == 'full' else 0
    profile = PITCH_PROFILES[pitch.pitch_type]
    if swing.swing == 'power':
        quality += (batter.power - 5) * 4 + POWER_QUALITY_BONUS
    quality -= (pitcher.velocity + profile.velocity - 5) * 2   # 球速压制
    if profile.break_amount:
        quality -= (pitcher.breaking - 5) * 2 * profile.break_amount
    quality += rng.randint(-8, 8)
    quality = max(5, min(100, quality))
    if swing.swing == 'ground':
        # 滚地球打法：把球压在地上打——质量封顶，球型一定是滚地
        quality = min(quality, GROUND_QUALITY_CAP)

    homerun = (quality >= HOMERUN_QUALITY and rng.random() < min(
        HOMERUN_CHANCE_CAP,
        0.05 + (quality - HOMERUN_QUALITY) * HOMERUN_CHANCE_STEP))
    if homerun:
        kind = 'fly'
    elif swing.swing == 'ground':
        kind = 'ground'                       # 滚地球：不打飞
    elif quality >= 66:
        kind = rng.choice(('fly', 'line'))
    elif quality >= 44:
        kind = rng.choice(('line', 'ground'))
    else:
        kind = rng.choice(('ground', 'ground', 'line'))

    low, high = BALL_KINDS[kind]['cells']
    if homerun:
        landing = FIELD_CELLS
    else:
        reach = max(1, (high - low) // 2)
        center = low + reach
        bias = -1 if swing.timing == 'early' else (
            1 if swing.timing == 'late' else 0)
        landing = max(low, min(high, center + bias * 2
                               + rng.randint(-reach, reach)))
    # 打得越结实，刚出手时落点范围越宽：看不清是"击球质量"的后果，不是随机噪声
    half = SPAN_HALF_MIN + (SPAN_HALF_MAX - SPAN_HALF_MIN) * quality / 100
    offset = rng.uniform(*SPAN_OFFSET) * half * rng.choice((-1, 1))
    shown = landing + offset
    if not FIELD_START <= shown <= FIELD_CELLS:
        shown = landing - offset              # 贴着场地边缘时，范围往场里偏
    ticks, tick_ms = flight_steps(kind, landing)
    return HitBall(
        kind=kind, landing=landing, shown=shown, spread=half, ticks=ticks,
        tick_ms=tick_ms, homerun=homerun, quality=quality,
    )


def flight_steps(kind: str, landing: int) -> tuple[int, int]:
    """一格一拍：跨几格就飞几拍，每拍时长固定（球型决定一格多少毫秒）。"""
    return max(1, landing - FIELD_START), BALL_KINDS[kind]['cell_ms']


def flight_run_speed(speed: int, ticks: int, tick_ms: int) -> float:
    """飞行阶段野手每秒跑几格：整段飞行总共 3 格（速度 ≥7 双倍），匀速分摊到整段时间上。

    球飞得远不等于野手更快——这是"野手比球慢"的唯一来源：想追就一直追，
    只是追不快，不会在某一格突然被系统停住。
    2026-10-15 从 5 格降到 3 格：原来击进场内的球只有 9–12% 落地（真实棒球约 30%），
    打进场的球几乎等于出局，反而让"少打进场"（强挥）变成划算的选择。
    """
    total = FLIGHT_MOVE_CELLS * (2.0 if speed >= 7 else 1.0)
    return total / (max(1, ticks) * tick_ms / 1000)


def ground_run_speed(speed: int) -> float:
    """捡球阶段野手每秒跑几格：每拍 1 格（速度 ≥7 为 2 格）。"""
    return (2.0 if speed >= 7 else 1.0) / (TICK_MS / 1000)


def ball_position(hit: HitBall, tick: int) -> int:
    """球从 1 号位向落点推进：一拍正好一格，最后一拍抵达落点。"""
    span = hit.landing - FIELD_START
    if span <= 0 or hit.ticks <= 0:
        return hit.landing
    return min(hit.landing, FIELD_START + max(0, min(hit.ticks, tick)))


def field_label(cell: float) -> str:
    """格位说成人话：棋盘不画号位数字，位置一律用左/中/右表述。"""
    offset = round(cell) - FIELD_MID
    if offset == 0:
        return '中线'
    side = '左' if offset < 0 else '右'
    span = max(1, (FIELD_CELLS - FIELD_MID) // 3)
    distance = abs(offset)
    if distance <= span:
        return f'中线偏{side}'
    if distance <= span * 2:
        return f'{side}外野'
    return f'{side}边线'


# ── 落地之后：捡球 → 传球 → 跑垒判定 ──

TICK_SECONDS = 0.56           # 拍数计算基准；实际非投打拍长乘 PHASE_SLOWDOWN
TICK_MS = int(TICK_SECONDS * 1000) * PHASE_SLOWDOWN   # 捡球/传球一拍的实际时长
GROUND_MAX_TICKS = 20         # 捡球阶段的 tick 上限（超过视为控球结束）
ANIM_FRAME_MS = 70 * 2        # 投球段/挥棒段的公共帧长（慢 2 倍）
PITCH_ANIM_FRAMES = 9         # 投球段 9 帧 ≈ 1.26 秒（14 fps）
SWING_ANIM_FRAMES = 3         # 挥棒段 3 帧 ≈ 0.42 秒
COUNTDOWN_SECONDS = 3         # 两边交牌后的倒数：3→2→1 之后才开投（用户 2026-10-15 定）
COUNTDOWN_TICK_MS = 1000      # 倒数一秒一跳（这是"准备时间"，不跟着慢放）
RUNNER_BASE_TICKS = 12        # 跑一个垒的基础 tick 数（速度越高越少）
RUNNER_MIN_TICKS = 3
THROW_SPEED_BASE = 16.0       # 臂力 0 的传球初速（米/秒）
THROW_SPEED_PER_ARM = 2.2     # 每点臂力加成
CELL_LATERAL = 5.0            # 外野线一格 ≈ 5 米

# 场地坐标（米）：本垒在原点，一垒/三垒在两侧，二垒在正前方
BASE_POSITIONS = {
    '一垒': (19.4, 19.4),
    '二垒': (0.0, 38.8),
    '三垒': (-19.4, 19.4),
    '本垒': (0.0, 0.0),
}
BASE_ORDER = ('一垒', '二垒', '三垒', '本垒')
BASE_LABELS = ('', '一垒', '二垒', '三垒')
HOME = 4                      # 跑者的终点：绕完一圈回到本垒（垒位 0 是起点本垒）
# 球型的落点纵深（米）：滚地最近、高飞最远
BALL_DEPTH = {'ground': 25.0, 'line': 45.0, 'fly': 65.0}


def base_name(base: int) -> str:
    """垒位（1–3，4＝回到本垒）的名字。"""
    return BASE_LABELS[base] if base <= 3 else '本垒'


def base_number(name: str) -> int:
    """垒名对应的垒位：一垒 1 … 本垒 4。"""
    return BASE_ORDER.index(name) + 1


def ball_spot(cell: int, kind: str) -> tuple[float, float]:
    """落点的场地坐标：横向由格位决定，纵深由球型决定。"""
    lateral = (cell - (FIELD_CELLS + 1) / 2) * CELL_LATERAL
    return lateral, BALL_DEPTH[kind]


def throw_distance(cell: int, kind: str, base: str) -> float:
    """落点到某个垒包的传球距离（米）。"""
    lateral, depth = ball_spot(cell, kind)
    target_x, target_y = BASE_POSITIONS[base]
    return hypot(lateral - target_x, depth - target_y)


def base_distance(from_base: str, to_base: str) -> float:
    """垒包到垒包的距离（米）——转传（连续双杀）用这个。"""
    start = BASE_POSITIONS[from_base]
    target = BASE_POSITIONS[to_base]
    return hypot(start[0] - target[0], start[1] - target[1])


def delivery_frames() -> int:
    """投球段 + 挥棒段一共几帧（盗垒的人正好在这段时间里跑到垒）。"""
    return PITCH_ANIM_FRAMES + SWING_ANIM_FRAMES


def throw_ticks(distance: float, arm: int) -> int:
    """传球所需 tick 数：距离 ÷ 球速 ÷ tick 时长（至少 1）。"""
    speed = THROW_SPEED_BASE + THROW_SPEED_PER_ARM * arm
    return max(1, ceil(distance / speed / TICK_SECONDS))


def runner_ticks(speed: int) -> int:
    """跑者跑一个垒需要的 tick 数。"""
    return max(RUNNER_MIN_TICKS, RUNNER_BASE_TICKS - speed)


# ── 守备判定 ──

def shift_start(shift: str) -> int:
    """布阵决定外野手的起始格位（偏左/偏右在这里生效）。"""
    return _SHIFT_START[shift]


def jump_label(kind: str) -> str:
    """起跳在播报里的叫法：滚地球是飞扑、空中球是跳起（只用于播报）。"""
    return '飞扑' if kind == 'ground' else '跳起'


def coverage(airborne: bool, kind: str, fielder: FielderAttributes,
             shift: str) -> int:
    """接球覆盖格数：基础范围（起跳在空中时更大）+ 布阵加成 + 守备属性。"""
    cover = BASE_COVERAGE + (LUNGE_REACH_BONUS if airborne else 0)
    cover += _SHIFT_BONUS.get(shift, {}).get(kind, 0)    # 只有部分布阵有加成
    if fielder.fielding >= 7:
        cover += 1
    return cover


@dataclass(frozen=True)
class FieldingResult:
    caught: bool                 # 接杀（空中拦下）
    error: bool                  # 脱手失误：球滚开，跑者多跑一个垒
    homerun: bool = False


def resolve_fielding(hit: HitBall, position: float, airborne: bool,
                     fielder: FielderAttributes, shift: str,
                     rng: random.Random) -> FieldingResult:
    """判定接球：接杀 / 脱手失误 / 落地。

    除了"位置差多少 × 覆盖范围"，击球质量也会抬高脱手概率：
    打得越结实，越可能接不住（这就是球落地的主要来源）。
    球到的那一刻野手正好在空中，范围大但手更糙（`LUNGE_MISS`）。

    **滚地球永远不可能被接杀**（用户 2026-10-15 纠正）：它是地面球，野手只能拦下来
    再传垒——打者要在一垒**被封杀**才算出去；拦不到就是滚地穿出去（安打）。
    """
    if hit.homerun:
        return FieldingResult(False, False, homerun=True)

    gap = abs(position - hit.landing)
    overshoot = gap - coverage(airborne, hit.kind, fielder, shift)
    miss = FIELD_MISS_BASE + max(0.0, overshoot) * FIELD_MISS_PER_GAP
    miss += max(0, hit.quality - 45) * QUALITY_MISS_PER_POINT
    miss -= (fielder.fielding - 5) * 0.02
    if airborne:
        miss += LUNGE_MISS
    miss = max(0.02, min(0.92, miss))

    if hit.kind != 'ground' and overshoot <= 0 and rng.random() > miss:
        return FieldingResult(True, False)
    return FieldingResult(
        False, rng.random() < 0.12 + max(0.0, overshoot) * 0.05)


# ── 跑垒判定 ──

STEAL_BASE_CHANCE = 0.62      # 盗垒基础成功率（守方属性不参与，只看跑者速度与投手是否盯防）
STEAL_SPEED_STEP = 0.08
STEAL_MIN_CHANCE = 0.20
STEAL_MAX_CHANCE = 0.90
STEAL_HOLD_FACTOR = 0.5       # 投手盯住跑者：起跑判断更难，盗垒成功率打对折
HOLD_CONTACT_GIFT = 0.08      # 盯跑者的代价：投手分心，打者接触率 +8%

RUN_SCOPES = ('hold', 'lead', 'all')      # 盗垒范围（随打击交牌）
RUN_ORDERS = ('back', 'stop', 'go')       # 击出后的跑垒指令：撤回 / 停止 / 前进
DEFAULT_RUN_ORDER = 'go'                  # 击出后默认全体前进（2026-10-21 用户定）
# 盗垒菜单的取值与文案（顺序＝菜单顺序：中立项夹在中间，← → 正好对上方向）
STEAL_LABELS = {'lead': '领跑者盗垒', 'hold': '保持', 'all': '全体盗垒'}


def forced_bases(bases: list[int]) -> set[int]:
    """被迫进垒的垒包：打者上一垒把一垒的人挤走，被挤的人再挤下一个。"""
    occupied = set(bases)
    forced: set[int] = set()
    for base in (1, 2, 3):
        if base in occupied and (base == 1 or base - 1 in forced):
            forced.add(base)
    return forced


def steal_chance(speed: int, hold: str = 'no') -> float:
    """盗垒成功率：跟跑者速度与投手是否盯防有关。"""
    chance = STEAL_BASE_CHANCE + (speed - 5) * STEAL_SPEED_STEP
    if hold == 'yes':
        chance *= STEAL_HOLD_FACTOR
    return max(STEAL_MIN_CHANCE, min(STEAL_MAX_CHANCE, chance))


def resolve_caught(sent: bool, runners: int, outs_before: int,
                   fielder: FielderAttributes, runner_speed: int,
                   rng: random.Random) -> tuple[int, str]:
    """接杀：(新增出局数, 叫法)。

    接杀本身出局 1 人；有跑者提前离垒时可能被双杀（打者 + 一个跑者 = 2 出局）；
    已经两出局时不再双杀（双杀需要占两名打者）。
    """
    if sent and runners and outs_before < 2:
        chance = 0.42 + (fielder.arm - 5) * 0.05 \
            - (runner_speed - 5) * 0.06
        if rng.random() < max(0.05, min(0.9, chance)):
            return 2, '双杀'
    return 1, '接杀'


def place_runners(runners: list[int], batter_base: int,
                  advance: int) -> PlayOutcome:
    """推进跑者并结算得分，处理同垒冲突（保送、安打、长打共用）。"""
    spots: set[int] = set()
    runs = 0
    for base in reversed(sorted(runners)):
        target = base + advance
        while target in spots:
            target += 1
        if target > 3:
            runs += 1
            continue
        spots.add(target)
    batter = batter_base
    while batter in spots:
        batter += 1
    if batter <= 3:
        spots.add(batter)
    else:
        runs += 1
    return PlayOutcome(bases=sorted(spots), runs=runs)

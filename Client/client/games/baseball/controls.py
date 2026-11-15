"""棋盘下方的操作区：一级盘、二级菜单与按钮盘的数据和导航。

这里只有数据和纯逻辑（整体可深拷贝进交互状态）；发指令、起动画是 handler 的事。
操作区永远不空：手上有活就是 `MODE_ACT`，手上没活但下一步有表单就是 `MODE_PREVIEW`
（能翻能预选、发不出指令），只有「击球」键按不动时是 `MODE_IDLE`（用户 2026-10-15 定）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ...window_engine import Option, move_option_index
from .view import Board

MODE_ACT = 'act'
MODE_PREVIEW = 'preview'
MODE_IDLE = 'idle'

# 一级表单每一项的名字（二级菜单的标题也是它）
SET_LABELS = {
    'shift': '布阵', 'pitch_type': '球种', 'band': '区域', 'effort': '力度',
    'hold': '跑者', 'guess': '预判', 'swing': '挥棒', 'steal': '盗垒',
}
# 设置项 → 服务端下发的取值文案表
_VALUE_KEYS = {
    'shift': 'shifts', 'pitch_type': 'pitch_types', 'band': 'bands',
    'effort': 'efforts', 'hold': 'holds', 'guess': 'pitch_types',
    'swing': 'swings', 'steal': 'steals',
}

_PITCH_PARAMS = ('shift', 'pitch_type', 'band', 'effort')
_SWING_PARAMS = ('guess', 'swing')

# 一级盘的身份：身份变了才说明该换一套选项（光标也跟着重置）
KIND_PITCH = 'pitch'
KIND_SWING = 'swing'
KIND_RELEASE = 'release'
KIND_HIT = 'hit'
KIND_SEND = 'send'
KIND_TAG = 'tag'
KIND_FLIGHT = 'flight'
KIND_GROUND_MOVE = 'ground-move'
KIND_GROUND_THROW = 'ground-throw'
_FORM_KINDS = (KIND_PITCH, KIND_SWING)


@dataclass(frozen=True)
class Item:
    """操作区里的一项：表单行、二级菜单的取值，或按钮盘里的一个按钮。"""

    label: str
    desc: str = ''           # 一级表单右侧的当前取值
    action: str = 'send'     # open / set / back / confirm / submit / hit / release / send
    command: str = ''        # send / submit 的完整指令
    param: str = ''          # open / set 的设置项
    value: str = ''          # set 的取值
    move: str | None = None  # 追球按钮的方向：'left' / 'right'；''＝停止；None＝不是追球
    live: bool = False       # 光标落下即生效（可撤销）；传垒那种要回车
    home: bool = False       # 中立项（停止 / 不传）或当前生效的那个：按钮盘的默认光标
    row: int = -1            # 按钮盘里的行号；-1＝不在按钮盘里

    @property
    def fires_on_cursor(self) -> bool:
        """光标落下就等于执行：追球、跑垒。"""
        return self.move is not None or self.live


BACK = Item('返回', action='back')
DECLINE = Item('否', action='back')
HIT =  Item('击球', action='hit')           # 只吃回车：要你在球到的那一刻按
RELEASE = Item('投球', action='release')   # 倒数完把球投出去（只是确认，不看时机）
MOVE_ROW = (Item('左移', move='left'),
            Item('停止', move='', home=True),    # 中立项夹在中间：← → 正好对上方向
            Item('右移', move='right'))
# 球在飞的时候，同一排按钮的回车是起跳：球正好在空中到，接球范围大但更糙
JUMP_ROW = tuple(replace(item, command='/jump') for item in MOVE_ROW)
# 跑垒：同一套手感——光标落到哪个，跑者就照那个跑（前进＝一个垒接一个垒，停止＝到下一个垒就站住，
# 撤回＝半路调头）；默认光标停在服务端此刻的指令上
RUN_LABELS = (('back', '撤回'), ('stop', '停止'), ('go', '前进'))


def _run_row(order: str = 'go') -> tuple[Item, ...]:
    return tuple(Item(label, command=f'/run {key}', live=True,
                      home=key == order) for key, label in RUN_LABELS)


def _pad(*rows: tuple[Item, ...]) -> list[Item]:
    """把几行按钮摊平成一个列表，并标上所在行。"""
    return [replace(item, row=row)
            for row, items in enumerate(rows) for item in items]


@dataclass
class Form:
    """这一球设置到哪了：投手的布阵 / 球种 / 区域 / 力度 / 牵制，打者的预判 / 挥棒 / 盗垒。

    全留在本地，提交那一刻才拼成完整指令；只有布阵立刻同步给服务端。
    """

    shift: str
    pitch_type: str
    band: str
    effort: str
    hold: str
    guess: str
    swing: str
    steal: str = 'hold'

    @classmethod
    def initial(cls, board: Board) -> Form:
        def first(key: str) -> str:
            return board.values(key)[0][0]

        return cls(board.shift, first('pitch_types'), first('bands'),
                   first('efforts'), first('holds'), first('pitch_types'),
                   first('swings'))

    def pitch_command(self, board: Board) -> str:
        """垒上没人时没有跑者可牵制：一律按「不牵制」交。"""
        hold = self.hold if board.bases else board.values('holds')[0][0]
        return (f'/pitch {self.pitch_type} {self.band} {self.effort} {hold}')

    def swing_command(self, board: Board) -> str:
        steal = self.steal if board.bases else 'hold'
        return f'/swing {self.guess} {self.swing} {steal}'

    def label(self, param: str, board: Board) -> str:
        """这一项当前取值的文案。"""
        return dict(board.values(_VALUE_KEYS[param]))[getattr(self, param)]


def _setting(board: Board, form: Form, param: str) -> Item:
    return Item(SET_LABELS[param], desc=form.label(param, board),
                action='open', param=param)


def _pitch_menu(board: Board, form: Form) -> list[Item]:
    """投手表单：布阵 / 球种 / 区域 / 力度 /（垒上有人才有）跑者 / 确定。"""
    params = _PITCH_PARAMS + (('hold',) if board.bases else ())
    return [_setting(board, form, param) for param in params] + [
        Item('确定', action='confirm', command=form.pitch_command(board))]


def _swing_menu(board: Board, form: Form) -> list[Item]:
    """打者表单：预判 / 挥棒 /（垒上有人才有）盗垒 / 确定。"""
    params = _SWING_PARAMS + (('steal',) if board.bases else ())
    return [_setting(board, form, param) for param in params] + [
        Item('确定', action='confirm', command=form.swing_command(board))]


def _throw_row(options) -> tuple[Item, ...]:
    """传球按钮：按距离列出各垒包 + 不传（回车才传，不可撤销）。"""
    return (*(Item(f'传{option.base}', command=f'/throw {option.base}')
              for option in options),
            Item('不传', command='/hold', home=True))


@dataclass
class Plan:
    """当前阶段该摆出什么：一级盘的身份、内容，以及按得动还是只是预告。"""

    kind: str
    items: list[Item]
    mode: str


def plan_for(board: Board, form: Form) -> Plan | None:
    """按阶段与身份决定操作区（空面板只有比赛结束后才有）。

    **预告**：动画期间双方都交完牌在等、传球途中守方也在等，操作区先把下一刻的菜单放出来，
    游标可以先摆好，阶段一到就原地生效。预告的只有**与结果无关**的那一套——
    接球起跳（回车）与攻方的跑垒键等球真被击出才上，不然就等于提前把"球有没有被打中"漏给打者。
    """
    phase = board.phase
    if board.fielding_side:
        if phase == 'call':
            if board.ready_fielding:        # 交完牌：球在手上，倒数完才亮
                return Plan(KIND_RELEASE, _pad((RELEASE,)),
                            MODE_ACT if board.armed else MODE_PREVIEW)
            return Plan(KIND_PITCH, _pitch_menu(board, form), MODE_ACT)
        if phase == 'delivery':
            return Plan(KIND_FLIGHT, _pad(JUMP_ROW), MODE_PREVIEW)
        if phase == 'flight':
            return Plan(KIND_FLIGHT, _pad(JUMP_ROW), MODE_ACT)
        if phase == 'throw':
            return Plan(KIND_GROUND_THROW,
                        _pad(_throw_row(board.throw.options)), MODE_PREVIEW)
        if phase == 'ground':
            if board.ground.at_ball:
                return Plan(KIND_GROUND_THROW,
                            _pad(_throw_row(board.ground.options)), MODE_ACT)
            return Plan(KIND_GROUND_MOVE, _pad(MOVE_ROW), MODE_ACT)
        if phase == 'tag':                  # 守方没动作：先摆下一球的投球表单
            return Plan(KIND_PITCH, _pitch_menu(board, form), MODE_PREVIEW)
        return None
    if phase == 'call':
        if board.ready_batting:             # 交完牌就把「击球」键放出来，暗的、按不动
            return Plan(KIND_HIT, _pad((HIT,)), MODE_IDLE)
        return Plan(KIND_SWING, _swing_menu(board, form), MODE_ACT)
    if phase == 'delivery':
        if not board.delivery.swung:        # 投球段与挥棒段都留着这颗键（不能消失）
            return Plan(KIND_HIT, _pad((HIT,)), MODE_ACT)
        return Plan(KIND_SEND, _pad(_run_row(board.run_order)), MODE_PREVIEW)
    if phase == 'tag':                      # 触垒窗口是一次新的决定：光标回到「停止」（不冒险）
        return Plan(KIND_TAG, _pad(_run_row('stop')), MODE_ACT)
    if phase in ('flight', 'ground', 'throw') and (
            board.bases or board.runners):
        return Plan(KIND_SEND, _pad(_run_row(board.run_order)), MODE_ACT)
    return None


@dataclass
class Frame:
    """二级菜单压栈时留下的一级菜单现场。"""

    items: list[Item]
    cursor: int
    title: str


@dataclass
class Controls:
    """操作区的现场：当前这一屏、光标、二级菜单栈，以及按钮盘每行生效的按钮。"""

    plan: Plan | None = None
    items: list[Item] = field(default_factory=list)
    cursor: int = 0
    title: str = ''                       # 二级菜单标题；一级主盘永远留空
    stack: list[Frame] = field(default_factory=list)
    pad_cursor: dict[int, int] = field(default_factory=dict)
    move: str = ''                        # 持续追球方向：''＝停止
    rest_on_submit: bool = False          # 交过牌：下一球的表单光标停在「确定」

    @property
    def mode(self) -> str:
        return self.plan.mode if self.plan else MODE_IDLE

    @property
    def kind(self) -> str:
        return self.plan.kind if self.plan else ''

    @property
    def is_pad(self) -> bool:
        return any(item.row >= 0 for item in self.items)

    # ── 跟着服务端状态走 ──

    def sync(self, board: Board, form: Form) -> None:
        """按最新局面重建一级盘；正在选值时二级菜单不被打断。"""
        plan = plan_for(board, form)
        changed = (plan.kind if plan else '') != self.kind
        self.plan = plan
        root = plan.items if plan else []
        if self.stack:
            self.stack[0].items = root          # 「返回」回到的是最新的一级盘
            if not changed:
                return
        if changed:
            self.stack = []
            self.title = ''
            self.pad_cursor = {}
            if not any(item.move is not None for item in root):
                self.move = ''                  # 这一盘没有跑位按钮，方向随之取消
            self.items = root
            self.cursor = self._initial_cursor()
            if self.is_pad:
                self._remember_cursor()
        else:
            self.items = root
            self.cursor = min(self.cursor, max(0, len(root) - 1))

    def _initial_cursor(self) -> int:
        """新换上的一盘光标停哪：按钮盘停在生效的那个（追球延续方向），表单停在第一项，
        交过牌之后的表单停在「确定」。"""
        if self.is_pad:
            if self.move:
                for index, item in enumerate(self.items):
                    if item.move == self.move:
                        return index
            return next((index for index, item in enumerate(self.items)
                         if item.home), 0)
        if self.rest_on_submit and self.kind in _FORM_KINDS:
            return next(index for index, item in enumerate(self.items)
                        if item.action == 'confirm')
        return 0

    def _remember_cursor(self) -> None:
        """记下每一行当前生效的那个按钮：换行回来时，光标要对得上实际生效的策略。"""
        if 0 <= self.cursor < len(self.items):
            self.pad_cursor[self.items[self.cursor].row] = self.cursor

    # ── 二级菜单 ──

    def _push(self) -> None:
        self.stack.append(Frame(self.items, self.cursor, self.title))

    def _pop(self) -> None:
        frame = self.stack.pop()
        self.items, self.cursor, self.title = (
            frame.items, frame.cursor, frame.title)

    def close_to_root(self) -> None:
        """把子菜单栈整个弹掉，回到当前阶段的一级盘（游标停在第一项）。"""
        self.stack = []
        self.items = self.plan.items if self.plan else []
        self.title = ''
        self.cursor = 0

    def after_hit(self) -> None:
        """打者一按下击球，操作区立刻换成跑垒布局（先站好位）：默认停在「前进」（击出后默认全体前进）。

        这一刻还在投打动画里，跑垒键只是预告；服务端的回执来了也是同一盘，光标不跳。
        """
        self.plan = Plan(KIND_SEND, _pad(_run_row()), MODE_PREVIEW)
        self.stack = []
        self.title = ''
        self.items = self.plan.items
        self.cursor = self._initial_cursor()
        self.pad_cursor = {}
        self._remember_cursor()

    def _open(self, param: str, board: Board, form: Form) -> None:
        """进入某一项的二级菜单：取值列表 + 返回，游标先停在当前取值上。"""
        self._push()
        self.title = SET_LABELS[param]
        values = list(board.values(_VALUE_KEYS[param]))
        self.items = [Item(label, action='set', param=param, value=value)
                      for value, label in values] + [BACK]
        keys = [value for value, _ in values]
        self.cursor = keys.index(getattr(form, param))

    def _open_confirm(self, item: Item) -> None:
        """提交前再问一次；指令是打开这一屏时按最新设置拼好的。"""
        self._push()
        self.title = item.label
        self.items = [Item('是', action='submit',         command=item.command), DECLINE]
        self.cursor = 0

    # ── 按键 ──

    def navigate(self, direction: str, mode: str) -> Item | None:
        """方向键：只挪光标。按钮盘里光标落到哪个按钮、那个按钮就立刻生效，
        这时返回它（传垒那一行不可撤销，光标挪过去不发货，返回 None）。"""
        if not self.items:
            return None
        if self.is_pad:
            return self._navigate_pad(direction, mode)
        step = {'left': -1, 'up': -1, 'right': 1, 'down': 1}.get(direction)
        if step is not None:
            self.cursor = self._step(range(len(self.items)), step)
        return None

    def _step(self, indices, step: int) -> int:
        """沿着给定的一串下标挪一格，到头环绕（和 UNO / Ludo / 所有菜单同一套语义）。"""
        indices = list(indices)
        landing = move_option_index(
            (Option(str(i), self.items[i].label) for i in indices),
            indices.index(self.cursor), step)
        return indices[landing]

    def _rows(self) -> list[list[int]]:
        rows: dict[int, list[int]] = {}
        for index, item in enumerate(self.items):
            rows.setdefault(item.row, []).append(index)
        return [rows[row] for row in sorted(rows)]

    def _navigate_pad(self, direction: str, mode: str) -> Item | None:
        rows = self._rows()
        current = next(i for i, row in enumerate(rows) if self.cursor in row)
        if direction in ('up', 'down'):
            target = current + (-1 if direction == 'up' else 1)
            if 0 <= target < len(rows):         # 换行本身不执行动作
                saved = self.pad_cursor.get(target)
                self.cursor = (saved if saved in rows[target]
                               else rows[target][0])
            return None
        if direction not in ('left', 'right'):
            return None
        landing = self._step(rows[current], -1 if direction == 'left' else 1)
        if landing == self.cursor:
            return None                         # 只有一个按钮的行：挪了也是原地
        self.cursor = landing
        self._remember_cursor()
        item = self.items[landing]
        return item if mode == MODE_ACT and item.fires_on_cursor else None

    def _refresh(self, board: Board, form: Form) -> None:
        """表单取值变了：一级盘上的当前取值与「确定」要提交的指令跟着更新。"""
        self.plan = plan_for(board, form)
        root = self.plan.items if self.plan else []
        if self.stack:
            self.stack[0].items = root
        else:
            self.items = root

    def enter(self, mode: str, board: Board, form: Form) -> Item | None:
        """回车：菜单内部的翻页（进二级 / 选值 / 返回 / 确认）在这里做完；
        需要发指令、开球或同步布阵时返回对应的项。预告期间只能翻菜单、摆游标。"""
        item = self.items[self.cursor]
        if item.action == 'open' and not self.stack:
            self._open(item.param, board, form)
        elif item.action == 'set':
            setattr(form, item.param, item.value)
            self._pop()
            self._refresh(board, form)
            return item if item.param == 'shift' else None   # 布阵要同步给服务端
        elif item.action == 'back':
            self._pop()
        elif mode == MODE_ACT:
            if item.action == 'confirm':
                self._open_confirm(item)
            else:
                return item
        return None

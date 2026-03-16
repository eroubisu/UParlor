# 游戏注册完整指导（AI 工作文档）

本文档是 AI 在帮用户注册新游戏时的操作手册。包含所有接口定义、文件结构、数据格式和约束条件。

---

## 一、注册总览

注册一个新游戏涉及 **服务端** 和 **客户端** 两部分，通过 `game_type` 字符串关联。框架核心代码 **零修改**。

### 必须创建的文件

| 文件          | 位置                          | 用途                     |
| ------------- | ----------------------------- | ------------------------ |
| `__init__.py` | `Server/server/games/<game>/` | 定义 GAME_INFO           |
| `engine.py`   | `Server/server/games/<game>/` | 实现 GameEngine protocol |

### 必须修改的文件

| 文件                              | 修改内容                                                            |
| --------------------------------- | ------------------------------------------------------------------- |
| `Server/server/games/__init__.py` | 底部添加 `from . import <game>` + `register_game('<game>', <game>)` |

### 可选创建的文件

| 文件               | 位置                               | 用途             | 不创建时的行为                           |
| ------------------ | ---------------------------------- | ---------------- | ---------------------------------------- |
| `commands.json`    | `Server/server/games/<game>/`      | 游戏各位置的指令 | 引擎 `get_commands()` 动态返回，或无指令 |
| `ranks.json`       | `Server/server/games/<game>/`      | 段位体系         | 无段位                                   |
| `titles.json`      | `Server/server/games/<game>/`      | 头衔定义         | 无游戏专属头衔                           |
| `items.json`       | `Server/server/games/<game>/`      | 物品定义         | 无游戏专属物品                           |
| `player_data.json` | `Server/server/games/<game>/`      | 新用户默认数据   | 无初始游戏数据                           |
| `help.md`          | `Server/server/games/<game>/`      | 帮助文本         | 显示 GAME_INFO 基本信息                  |
| handler `.py`      | `Client/client/protocol/` 或独立包 | 客户端事件处理   | 无客户端游戏事件处理                     |
| renderer `.py`     | `Client/client/protocol/` 或独立包 | 客户端游戏渲染   | game_board 面板显示 fallback 文本        |

---

## 二、服务端：GAME_INFO

在 `Server/server/games/<game>/__init__.py` 中定义。这是唯一的代码级配置。

```python
from .engine import MyGameEngine

GAME_INFO = {
    # ── 必填 ──
    'id': 'mygame',                    # 唯一标识，同时是 /play 参数
    'name': '我的游戏',                 # 游戏列表显示名
    'icon': '◆',                       # 游戏列表图标（纯文本字符，禁止 emoji）
    'description': '一句话描述',
    'min_players': 2,
    'max_players': 4,
    'create_engine': lambda: MyGameEngine(),

    # ── 引擎模式（必填）──
    'per_player': False,
    # False = 房间制：共享引擎实例，管理多个房间（棋牌类）
    # True  = 玩家制：每个玩家独立引擎实例（RPG/单人类）

    # ── 位置层级（必填）──
    # 格式: {位置ID: (显示名称, 父位置)}
    # 至少一个位置的 parent 必须是 'lobby'（作为游戏根位置）
    'locations': {
        'mygame':         ('我的游戏', 'lobby'),       # 游戏根（进入点）
        'mygame_room':    ('房间',     'mygame'),       # 房间级
        'mygame_playing': ('对局中',   'mygame_room'),  # 游戏进行中
    },

    # ── 可选 ──
    'create_bot_scheduler': lambda server: MyBotScheduler(server),
}
```

### 位置命名约束

- 位置 ID 建议以 `game_id` 作为前缀（如 `chess`, `chess_room`, `chess_playing`）
- 框架按 `locations` 字典匹配位置归属游戏，后备按前缀匹配
- `lobby` 和 `profile` 是框架保留位置，不可使用

### 引擎模式区别

|              | 房间制 `per_player=False` | 玩家制 `per_player=True` |
| ------------ | ------------------------- | ------------------------ |
| 引擎实例 key | `game_id`                 | `game_id_玩家名`         |
| 引擎生命周期 | 服务器运行期间持续存在    | 玩家断线后销毁           |
| 适用场景     | 棋牌、竞技                | RPG、单人冒险、MMO       |
| 多房间管理   | 引擎内部自行管理          | 每实例一个玩家           |

---

## 三、服务端：GameEngine Protocol

定义在 `Server/server/game/protocol.py`。引擎必须实现以下 5 个方法：

### 3.1 必须实现

```python
class GameEngine(Protocol):
    def handle_command(self, lobby, player_name, player_data, cmd, args) -> Any:
        """处理游戏指令

        参数:
            lobby: LobbyEngine 实例（提供位置管理、玩家查询等框架服务）
            player_name: 发指令的玩家名
            player_data: 玩家完整数据 dict（可读写，由框架持久化）
            cmd: 指令名（已 lower()，如 '/move' → 'move'）
            args: 指令参数（cmd 之后的全部文本）

        返回:
            str   — 纯文本消息，框架作为 game 类型发给 caller
            dict  — Rich Result（见第五节）
            None  — 表示未匹配此指令（框架继续尝试其他处理器）
        """

    def handle_disconnect(self, lobby, player_name) -> list[dict]:
        """玩家断线处理。返回需要发送给其他玩家的通知列表。"""

    def handle_back(self, lobby, player_name, player_data) -> Any:
        """处理 /back（返回上一级）。返回格式同 handle_command。"""

    def handle_quit(self, lobby, player_name, player_data) -> Any:
        """处理 /home（直接回大厅）。返回格式同 handle_command。"""

    def get_welcome_message(self, player_data) -> dict:
        """进入游戏时的欢迎信息 + 初始 room_data

        典型返回:
        {
            'action': 'location_update',
            'message': '欢迎来到我的游戏！',
            'room_data': {...},           # 可选，初始游戏状态
            'send_to_caller': [           # 可选，Rich Result 模式
                {'type': 'game', 'text': '欢迎！'},
                {'type': 'room_update', 'room_data': {...}},
            ],
        }
        """
```

### 3.2 可选方法（继承 BaseGameEngine 获得默认空实现）

```python
class BaseGameEngine:
    def get_commands(self, lobby, location, player_name, player_data) -> list[dict] | None:
        """动态返回当前位置的指令列表。返回 None 时 fallback 到 commands.json。
        返回格式: [{"name": "move", "label": "走棋", "desc": "move <位置>", "tab": "游戏"}]"""
        return None

    def get_profile_extras(self, player_data) -> str | None:
        """个人资料附加行（如段位、胜率）"""
        return None

    def get_status_extras(self, player_name, player_data) -> dict | None:
        """状态消息附加字段（附加到 StatusUpdate 中）"""
        return None

    def get_player_room(self, player_name):
        """查询玩家所在房间对象"""
        return None

    def get_player_room_data(self, player_name) -> dict | None:
        """查询玩家视角的房间状态 dict（RoomUpdate 的 room_data）
        这个 dict 会整体发送给客户端，存入 state.game_board.room_data"""
        return None

    def report_game_result(self, lobby, player_name, player_data, result, game_specific=None):
        """报告游戏结果。result: 'win'|'loss'|'draw'
        自动更新 player_data['game_stats'] 并检查头衔。
        game_specific: 游戏专属统计增量 dict（累加到 player_data[game_key]['stats']）"""

    def leave_room(self, player_name):
        """离开房间清理"""
```

---

## 四、服务端：BaseRoomCommandHandler

定义在 `Server/server/game/room_handler.py`，为**房间制游戏**提供共享指令处理逻辑。

提供的现成功能：`/cancel`, `/rank`, `/invite`, `/accept`, `/join`, `/bot`, `/kick` + 段位结算。

子类需实现的抽象属性/方法：

```python
class MyCommandHandler(BaseRoomCommandHandler):
    game_key = 'mygame'               # player_data 中的游戏数据键名
    game_name = '我的游戏'
    action_prefix = 'mygame'          # Rich Result action 前缀
    max_players = 4
    room_location = 'mygame_room'
    playing_location = 'mygame_playing'

    def _get_match_types(self):
        """返回匹配类型列表: [{"id": "ranked", "name": "排位赛"}, ...]"""

    def _get_title_checks(self, stats):
        """返回头衔检查条件列表"""

    def _get_rank_points_change(self, rank, result_data):
        """计算段位分变化量"""

    def _format_stats(self, player_data):
        """格式化玩家统计信息文本"""

    def _format_room_list(self, rooms):
        """格式化房间列表文本"""

    def _iter_ranked_players(self, room, result_data):
        """迭代需要结算段位的玩家: yield (player_name, 'win'|'loss'|'draw')"""
```

辅助方法（直接使用）：

| 方法                                                                       | 用途                        |
| -------------------------------------------------------------------------- | --------------------------- |
| `_iter_room_players(room, exclude)`                                        | 迭代房间内真人玩家          |
| `_build_notify_players(room, msg, room_data, exclude, location)`           | 构造发给房间玩家的消息 dict |
| `_build_game_notify(room, msg, room_data, exclude, location, update_last)` | 构造文字 + room_update      |
| `_process_ranked_result(lobby, room, result_data)`                         | 执行段位结算                |

---

## 五、Rich Result Protocol

`handle_command` 等方法返回 dict 时，由 `result_dispatcher.py` 的 `dispatch_game_result()` 分发。

```python
{
    # ── 给指令发起者 ──
    'send_to_caller': [
        {'type': 'game', 'text': '你走了 e4'},                    # 文字消息
        {'type': 'room_update', 'room_data': {...}},               # 更新游戏面板
        {'type': 'location_update', 'location': 'chess_playing'},  # 位置变更
        {'type': 'room_leave', 'location': 'lobby'},               # 离开房间
    ],

    # ── 给其他玩家 ──
    'send_to_players': {
        '玩家A': [{'type': 'game', 'text': '对手走了 e4'}],
        '玩家B': [{'type': 'room_update', 'room_data': {...}}],
    },

    # ── 框架动作 ──
    'action': 'location_update',  # 触发位置变更处理
    'save': True,                 # 保存玩家数据
    'refresh_commands': True,     # 刷新所有涉及玩家的指令列表

    # ── Bot 调度 ──
    'schedule': [{'game_id': 'chess', 'task': 'bot_move', 'delay': 1.0}],
}
```

### 消息类型

| type              | 用途         | 客户端处理                                    |
| ----------------- | ------------ | --------------------------------------------- |
| `game`            | 游戏文本消息 | 显示在指令面板                                |
| `room_update`     | 游戏面板状态 | 存入 `state.game_board.room_data`，触发渲染器 |
| `location_update` | 位置变更     | 更新面包屑、刷新指令                          |
| `room_leave`      | 离开房间     | 清空 game_board，更新位置                     |
| 其他任意 type     | 游戏特有事件 | 自动包装为 `game_event` → 路由到 Handler      |

**关键机制**：`send_to_caller` 和 `send_to_players` 中的消息，框架级类型（`game`, `room_update`, `location_update` 等）直接透传，**游戏特有类型**（如 `hand_update`, `animation`）自动包装为：

```json
{"type": "game_event", "game_type": "mygame", "event": "hand_update", "data": {...}}
```

---

## 六、服务端：可选 JSON 文件格式

### commands.json

```json
{
  "mygame": [
    {
      "name": "create",
      "label": "创建房间",
      "desc": "create [类型]",
      "tab": "游戏"
    },
    {
      "name": "list",
      "label": "房间列表",
      "desc": "查看所有房间",
      "tab": "游戏"
    }
  ],
  "mygame_room": [
    { "name": "start", "label": "开始", "desc": "开始游戏", "tab": "游戏" },
    {
      "name": "invite",
      "label": "邀请",
      "desc": "invite <玩家>",
      "tab": "社交"
    }
  ],
  "mygame_playing": [
    { "name": "move", "label": "下棋", "desc": "move <位置>", "tab": "游戏" },
    { "name": "resign", "label": "认输", "desc": "放弃本局", "tab": "游戏" }
  ]
}
```

字段说明：

- `name`: 指令名（玩家输入 `/name`，框架传给引擎的 cmd 参数已去掉 `/`并 lower）
- `label`: 快捷键菜单中显示的标签
- `desc`: 帮助文本中的指令描述
- `tab`: 指令分组标签（同 tab 的指令归为一组显示）
- `scope`（可选）: `"inventory"` 等，控制显示条件

### ranks.json

```json
{
  "ranks": {
    "novice_1": { "name": "新手 I", "points_up": 100 },
    "novice_2": { "name": "新手 II", "points_up": 200 },
    "master": { "name": "大师", "points_up": null }
  },
  "rank_order": ["novice_1", "novice_2", "master"],
  "rank_to_title": {
    "master": "mygame_master_title_id"
  }
}
```

### titles.json

```json
{
  "titles": {
    "mygame_master": {
      "name": "棋圣",
      "description": "达到大师段位",
      "rarity": "legendary"
    }
  },
  "sources": {
    "mygame_achievement": {
      "name": "游戏成就",
      "titles": ["mygame_master"]
    }
  }
}
```

### items.json

```json
{
  "items": {
    "mygame_trophy": {
      "name": "冠军奖杯",
      "description": "赢得锦标赛获得",
      "stackable": true,
      "use_methods": ["display", "gift"]
    }
  },
  "sources": {
    "mygame_reward": {
      "name": "游戏奖励",
      "items": ["mygame_trophy"]
    }
  }
}
```

### player_data.json

```json
{
  "stats": {
    "wins": 0,
    "losses": 0
  },
  "rank": "novice_1",
  "rank_points": 0,
  "settings": {
    "auto_confirm": false
  }
}
```

新用户注册时，此内容自动写入 `player_data['mygame']`。

---

## 七、客户端：Handler

在 `Client/client/protocol/handler.py` 中定义了 Protocol 和注册表。

```python
from client.protocol.handler import GameClientHandler, GameHandlerContext, register_handler

class MyGameHandler:
    game_type = "mygame"   # 必须与服务端 GAME_INFO['id'] 一致

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        """处理 game_event 消息。event 是事件名，data 是事件数据 dict。
        返回 True 表示已处理。"""
        if event == "hand_update":
            # 通过 State 更新，触发渲染器重绘
            ctx.state.game_board.update_room(data.get("room_data", {}))
            return True
        if event == "animation":
            # 可以用定时器做动画
            ctx.cmd_add_line("动画效果...")
            return True
        return False

    def on_enter_game(self, ctx: GameHandlerContext) -> None:
        """进入游戏位置时调用。确保面板存在。"""
        ctx.ensure_panel('game_board')

    def on_leave_game(self, ctx: GameHandlerContext) -> None:
        """离开游戏时调用。清理面板。"""
        ctx.state.game_board.clear()

register_handler(MyGameHandler())
```

### GameHandlerContext 接口

| 方法                             | 用途                                                         |
| -------------------------------- | ------------------------------------------------------------ |
| `ctx.state`                      | `ModuleStateManager`，全局状态（只读/写 State，不碰 Widget） |
| `ctx.cmd_add_line(text)`         | State + Widget 都更新（持久化）                              |
| `ctx.cmd_widget_add_line(text)`  | 仅 Widget（用于动画等临时显示，不持久化）                    |
| `ctx.set_timer(delay, callback)` | 延时回调                                                     |
| `ctx.ensure_panel(module_name)`  | 确保面板存在于布局                                           |
| `ctx.remove_panel(module_name)`  | 移除面板                                                     |

**约束**：Handler **禁止直接访问 Widget**。必须通过 Context 或 State。

### Handler 可选方法（AI 感知相关）

```python
def ai_describe(self, room_data: dict) -> str:
    """为 AI 伙伴提供可读的游戏状态描述。
    框架在 AI 的 look_game_room 工具调用时使用。
    不实现此方法时，框架回退到 room_data['ai_summary'] 或 JSON dump。
    截断上限 1500 字。"""
```

---

## 八、客户端：Renderer

在 `Client/client/protocol/renderer.py` 中定义了 Protocol 和注册表。

```python
from textual.widgets import RichLog
from client.protocol.renderer import register_renderer

class MyGameRenderer:
    game_type = "mygame"   # 必须与服务端 GAME_INFO['id'] 一致

    def render_board(self, log: RichLog, room_data: dict) -> None:
        """渲染游戏主画面。room_data 是服务端 get_player_room_data 返回的 dict。
        通过 log.write(text) 输出 Rich markup 文本。"""
        log.write("游戏画面")

    def render_status(self, log: RichLog, game_data: dict) -> None:
        """渲染游戏状态信息。"""
        log.write("状态")

    def render_board_waiting(self, log: RichLog, room_data: dict) -> None:
        """渲染等待中的房间（可选，不实现则不显示等待画面）。"""
        players = room_data.get('players', [])
        log.write(f"等待中... {len(players)}/{room_data.get('max_players', '?')}")

register_renderer(MyGameRenderer())
```

### 渲染触发链

```
RoomUpdate 消息 → dispatch.py → state.game_board.update_room(room_data)
    → State listener → GameBoardPanel._render_room(room_data)
        → get_renderer(room_data['game_type'])
            → room_data['state'] == 'waiting' ? render_board_waiting : render_board
```

### 无渲染器时

GameBoardPanel 显示 fallback 文本（room_data 的基本信息）。

---

## 九、客户端：自定义面板（可选）

如果游戏需要 game_board 以外的专属面板：

```python
# 在 Client/client/panels/__init__.py 中添加
from ..registry import register_module
from .my_game_panel import MyGamePanel

register_module('mygame_panel', '我的面板', MyGamePanel, scope='game')
```

Handler 中通过 `ctx.ensure_panel('mygame_panel')` 添加到布局。

---

## 十、AI 伙伴感知接入

游戏不需要做任何额外工作即可被 AI 感知。以下是渐进式接入层级：

| 投入 | AI 能看到什么                      | 实现方式                                               |
| ---- | ---------------------------------- | ------------------------------------------------------ | --------- |
| 零   | room_data JSON dump（1500 字截断） | 框架自动                                               |
| 低   | 游戏事件描述                       | room_data 或 GameEvent data 中加 `ai_description` 字段 |
| 中   | 可读的游戏状态摘要                 | Handler 实现 `ai_describe(room_data)`                  |
| 高   | 事件推送到 AI 主动搭话             | room_data/data 中加 `ai_priority: "high"               | "normal"` |

### AI 事件缓冲

`dispatch.py` 在收到 RoomUpdate 或 GameEvent 时，如果数据中包含 `ai_description` 字段，自动存入 `state.game_board.recent_events`（最多保留 10 条）。AI 调用 `look_game_room` 时附带最近 5 条。

### AI 主动搭话触发

数据中同时包含 `ai_priority` 字段时，事件进入 AI 注意力系统：

- `"normal"` — 进入被动感知缓冲区
- `"high"` — 触发 AI 主动搭话

---

## 十一、room_data 设计建议

`room_data` 是服务端通过 `get_player_room_data()` 返回给客户端的全量游戏状态快照。每次发送都是完整覆盖。

### 建议包含的标准字段

```python
{
    'game_type': 'mygame',           # 必须 — 客户端用来路由渲染器和处理器
    'state': 'waiting|playing|ended', # 建议 — 客户端判断调用哪个渲染方法
    'players': [...],                 # 建议 — 玩家列表
    # ... 游戏专属数据 ...
}
```

### AI 感知字段（可选，附加到 room_data 或 GameEvent data）

```python
{
    'ai_summary': '简短的游戏状态描述',        # 回退给 AI（无 ai_describe 时使用）
    'ai_description': '刚发生了什么的简述',     # 存入 AI 事件缓冲
    'ai_priority': 'high',                     # 触发 AI 主动搭话
}
```

---

## 十二、完整注册清单

### 最小可用（3 个文件 + 1 行修改）

1. `Server/server/games/mygame/__init__.py` — GAME_INFO
2. `Server/server/games/mygame/engine.py` — GameEngine 5 个方法
3. `Server/server/games/__init__.py` — 添加两行注册代码

此时：玩家可 `/play mygame`，引擎可处理指令，游戏文本消息显示在指令面板。

### 基础体验（+ 3 个文件）

4. `Server/server/games/mygame/commands.json` — 指令提示
5. 客户端 Handler — 处理 game_event
6. 客户端 Renderer — 渲染 game_board 面板

此时：有快捷键菜单、游戏画面渲染、游戏特有事件处理。

### 完整体验（按需）

7. `help.md` — 帮助文本
8. `ranks.json` — 段位体系
9. `titles.json` — 头衔
10. `items.json` — 物品
11. `player_data.json` — 新用户默认数据
12. Handler `ai_describe()` — AI 感知优化
13. 自定义面板 — 特殊 UI 需求

---

## 十三、约束与禁止

- **禁止修改框架核心文件**：`chat_server.py`, `lobby/engine.py`, `config.py`, `dispatch.py`, `screen.py`
- **禁止 Handler 直接访问 Widget**：必须通过 GameHandlerContext
- **禁止引擎访问 lobby 内部属性**：仅通过 lobby 公开方法和传入的 player_data 交互
- **禁止引擎 import 框架内部模块**：引擎只依赖传入参数和自身代码
- **禁止 UI 使用 emoji**：图标用纯文本字符（●○◆◇→←↑↓ 等）
- **禁止大厅 UI 使用彩色**：灰度色板。游戏内渲染可用彩色
- **禁止背景颜色**：所有 background 必须 transparent
- **指令定义写 JSON 而非 .py**（commands.json 或引擎 get_commands 动态返回）
- **game_type 全局唯一**：服务端 GAME_INFO['id']、客户端 Handler.game_type、Renderer.game_type 必须一致

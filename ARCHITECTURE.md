# UParlor 架构指南

终端多人游戏厅 — Python Textual 客户端 + asyncio Socket 服务端。

## 数据流

```
┌─ Server ─────────────────────────────────────────────────┐
│                                                          │
│  ChatServer (连接/认证/IO)                                │
│       ↓ command                                          │
│  LobbyEngine (指令路由/位置管理)                           │
│       ├─ GlobalHandler (help/clear/exit/title/use/gift)  │
│       └─ GameEngine.handle_command()                     │
│              ↓ result(dict)                              │
│  ResultDispatcher (Rich Result → 目标消息)                │
│       ↓ JSON                                             │
└──────────────────────────────────────────────────────────┘
       ↓ TCP Socket (JSON)
┌─ Client ─────────────────────────────────────────────────┐
│                                                          │
│  App._start_receive_worker() 接收                        │
│       ↓ raw dict                                         │
│  dispatch_server_message() (net/dispatch.py)             │
│       ├─ parse → typed dataclass (net/messages.py)       │
│       ├─ 更新 State (state.py)                           │
│       ├─ GameEvent → GameClientHandler.handle_event()    │
│       └─ AI 事件推送 (attention buffer)                   │
│                                                          │
│  State._notify() → Widget listener → UI 更新             │
│                                                          │
│  键盘输入:                                               │
│  KeyboardMixin.on_key() → VimMode 分流                   │
│       ├─ NORMAL: 面板导航/窗口切换/Space菜单              │
│       └─ INSERT: InputMixin._submit_input() → 面板路由   │
│              → App.send_command()/send_chat()             │
└──────────────────────────────────────────────────────────┘
```

## 目录职责

### Server/server/

| 目录/文件                   | 职责                                                                   |
| --------------------------- | ---------------------------------------------------------------------- |
| `chat_server.py`            | TCP 服务器主循环、连接管理、认证、消息 IO                              |
| `config.py`                 | 端口、路径、位置层级树、指令表加载                                     |
| `msg_types.py`              | 消息类型常量（GAME, ROOM_UPDATE, CHAT 等）                             |
| `lobby/engine.py`           | 指令路由（全局→导航→游戏引擎）、位置管理、引擎生命周期                 |
| `lobby/command_registry.py` | 全局指令处理器注册表（@register_global 装饰器）+ 子菜单构建器注册表    |
| `lobby/help.py`             | 帮助文档生成                                                           |
| `lobby/account.py`          | 账号操作（改密、改名、删号）                                           |
| `lobby/confirmation.py`     | 多步确认流程                                                           |
| `game/protocol.py`          | **GameEngine Protocol** + BaseGameEngine + GameEvent                   |
| `game/result_dispatcher.py` | Rich Result → 多目标消息分发、Action 处理器注册表                      |
| `game/room_handler.py`      | 房间制游戏基类模板（棋牌类）                                           |
| `games/__init__.py`         | 游戏注册框架（自动注入位置/段位/头衔/物品/配方到全局）                 |
| `games/world/`              | 开放世界游戏模块                                                       |
| `player/manager.py`         | 玩家数据文件 IO                                                        |
| `player/schema.py`          | 玩家数据模板 + 游戏字段注入 + 迁移                                     |
| `player/auth.py`            | 登录/注册逻辑                                                          |
| `systems/`                  | 跨游戏系统（ranks/titles/items/recipes/equipment/leveling/attributes） |
| `infra/`                    | 基础设施（聊天日志、私聊日志、维护任务、文本工具）                     |
| `data/`                     | 全局 JSON 数据（commands/ranks/titles/items/levels）                   |

### Client/client/

| 目录/文件              | 职责                                                                                      |
| ---------------------- | ----------------------------------------------------------------------------------------- | --- | ----------------- | ----------------------------------------------------- |
| `app.py`               | Textual App 生命周期、网络接收、Ping 心跳、AI 定时器                                      |
| `config.py`            | 唯一色板（灰度）、网络端口、面板行数限制、Rich 语义常量                                   |
| `state.py`             | 8 个 State 类（业务数据 SSOT）+ ModuleStateManager                                        |
| `registry.py`          | 模块注册表（name → label/class/scope）                                                    |
| `protocol/handler.py`  | **GameClientHandler Protocol** + GameHandlerContext + 注册表                              |
| `protocol/renderer.py` | **GameRenderer Protocol** + 注册表                                                        |
| `protocol/commands.py` | 指令缓存（服务端下发 → 按 Tab 分组 → Hint Bar 过滤）                                      |
| `net/dispatch.py`      | 消息路由（raw dict → State 更新 → AI 推送）                                               |
| `net/messages.py`      | 消息 dataclass 定义 + 解析器表                                                            |
| `net/connection.py`    | TCP 连接管理                                                                              |
| `ui/screen.py`         | GameScreen — 三个 Mixin 组合 + 布局管理 + Vim 模式桥接                                    |
| `ui/keyboard.py`       | KeyboardMixin — NORMAL/INSERT 键位分发                                                    |
| `ui/input_handler.py`  | InputMixin — 输入提交路由 + Hint Bar 交互                                                 |
| `ui/vim_mode.py`       | VimMode — 双模态 + IME 切换 + 数字前缀                                                    |
| `ui/layout.py`         | 窗格树（PaneNode/SplitNode）— 拆分/关闭/导航/序列化                                       |
| `ui/space_menu.py`     | SpaceMenuMixin — Space 快捷菜单                                                           |
| `panels/`              | UI 面板实现（chat/game_board/inventory/online/status/ai_chat/notification/command/login） | \n  | `panels/_render/` | 面板渲染辅助模块（card/status/ai_chat/ai_chat_views） |
| `widgets/`             | 共享组件（input_bar/menu_nav/tab_menu/prompt/scrollbar）                                  |
| `games/`               | 游戏客户端模块（world_handler + world_renderer）                                          |
| `ai/`                  | AI 伙伴系统（service/attention/memory/mood/social/persona/character/impression）          |

## 核心 Protocol 接口

### 服务端 GameEngine（game/protocol.py）

```
必须实现:
  handle_command(lobby, player_name, player_data, cmd, args) → str|dict|None
  handle_disconnect(lobby, player_name) → list[dict]
  handle_back(lobby, player_name, player_data) → Any
  handle_quit(lobby, player_name, player_data) → Any
  get_welcome_message(player_data) → dict

可选（BaseGameEngine 提供默认空实现）:
  get_commands(lobby, location, player_name, player_data) → list[dict]|None
  get_status_extras(player_name, player_data) → dict|None
  get_player_room(player_name) → Any
  get_player_room_data(player_name) → dict|None
  report_game_result(lobby, player_name, player_data, result, game_specific) → None
  leave_room(player_name) → None
```

### 客户端 GameClientHandler（protocol/handler.py）

```
必须实现:
  game_type: str
  handle_event(event, data, ctx: GameHandlerContext) → bool
  on_enter_game(ctx) → None
  on_leave_game(ctx) → None

GameHandlerContext 提供:
  .state                     — 全局 State（只读）
  .cmd_add_line(text)        — 指令面板追加行（State + Widget）
  .cmd_widget_add_line(text) — 仅 Widget（动画用）
  .set_timer(delay, cb)      — 延时回调
  .ensure_panel(module)      — 确保面板在布局中
  .remove_panel(module)      — 移除面板
  ._get_module(name)         — 获取面板实例（通过 _widget_call 安全调用）
```

### 客户端 GameRenderer（protocol/renderer.py）

```
必须实现:
  game_type: str
  render_board(room_data: dict) → RenderableType
```

## Rich Result 协议（服务端引擎返回格式）

```python
{
    'action': str,                              # location_update | game_action | 自定义
    'message': str,                             # 可选 — UI 消息
    'send_to_caller': [{'type': ..., ...}],     # 发给命令发起者
    'send_to_players': {'name': [msgs]},        # 发给指定玩家
    'schedule': [{'delay': float, ...}],        # 延时任务
    'save': bool,                               # 持久化 player_data
    'refresh_commands': bool,                   # 重新下发指令列表
}
```

游戏特有消息（非框架类型）自动包装为 `{"type": "game_event", "game_type": "...", "event": "...", "data": {...}}`。

### send_to_caller 消息类型

| type              | 客户端处理                                    |
| ----------------- | --------------------------------------------- |
| `game`            | 文本显示在指令面板                            |
| `room_update`     | 存入 `state.game_board.room_data`，触发渲染器 |
| `location_update` | 更新位置 + 面包屑 + 指令列表                  |
| `room_leave`      | 清空 game_board，返回指定位置                 |
| 其他任意 type     | 包装为 game_event → 路由到 Handler            |

### room_data 约定

服务端 `get_player_room_data()` 返回的 dict，必须含 `game_type`，建议含 `state`（waiting/playing/ended）和 `players`。 AI 感知可选字段：`ai_summary`（文本摘要）、`ai_description`（事件描述→缓冲区）、`ai_priority`（`"high"` 触发 AI 主动搭话）。

## 指令路由优先级

```
1. pending_confirms（多步确认流程）
2. GlobalHandler（command_registry.py 注册的全局处理器）
3. Navigation（/back → 父位置, /home → 城镇）
4. GameEngine.handle_command()（当前位置对应的游戏引擎）
```

指令列表来源优先级：engine.get_commands() > commands.json[location]

## 状态管理模式

```
BaseState (state.py)           Panel/Widget
─────────────────             ──────────────
业务数据存储                    纯 UI 渲染
add_listener(cb)   ─────→    _on_state_event(event, *args)
remove_listener(cb) ←─────   on_unmount() 中清理
_notify(event)     ─────→    更新渲染
```

- 所有 State 类继承 `BaseState`，提供统一的多监听器通知机制
- 业务数据只存 State，面板从 State 读取
- Widget 创建时调用 `restore(state)` 恢复全部内容，注册 `add_listener`
- Widget 销毁时调用 `remove_listener` 清理（`on_unmount`）

8 个 State 类: ChatState, CmdState, StatusState, OnlineState, GameBoardState, InventoryState, AIChatState, NotificationState + ModuleStateManager 统一管理

## AI 游戏感知

| 投入 | AI 能看到                          | 实现方式                                       |
| ---- | ---------------------------------- | ---------------------------------------------- |
| 零   | room_data JSON dump（1500 字截断） | 框架自动                                       |
| 低   | 事件描述文本                       | room_data/GameEvent 中加 `ai_description` 字段 |
| 中   | 可读的游戏状态摘要                 | Handler 实现 `ai_describe(room_data) → str`    |
| 高   | 事件推送 + AI 主动搭话             | 数据中加 `ai_priority: "high"`                 |

## 游戏模块注册流程

### 服务端

```
games/__init__.py 的 register_game(game_id, module):
  1. 读取 module.GAME_INFO
  2. 注入位置到 LOCATION_HIERARCHY
  3. 注入指令到 COMMAND_TABLE
  4. 注入 player_data 默认值到 schema
  5. 注入 ranks/titles/items/recipes 到全局系统
  6. 存入 GAMES[game_id]
```

### 客户端

```
games/__init__.py 导入模块 → 模块顶层调用:
  register_handler(WorldClientHandler())   # protocol/handler.py
  register_renderer(WorldRenderer())       # protocol/renderer.py
```

导入即注册，无需手动配置。

## 命名约定

| 前缀/模式    | 含义               | 示例                                         |
| ------------ | ------------------ | -------------------------------------------- |
| `cmd_X`      | 指令处理器函数     | `cmd_buy`, `cmd_sell`, `cmd_forge`           |
| `_handle_X`  | 内部事件处理       | `_handle_player_delta`, `_handle_navigation` |
| `_build_X`   | 数据构建           | `_build_map_update`, `_build_player_delta`   |
| `GAME_INFO`  | 游戏模块元信息字典 | `games/world/__init__.py`                    |
| `X_HANDLERS` | 指令路由表         | `BUILDING_HANDLERS = {'buy': cmd_buy}`       |
| `_PARSERS`   | 消息解析器表       | `net/messages.py`                            |

## 扩展点地图

### 添加新游戏

**模板**: `Server/server/games/_template/` 和 `Client/client/games/_template/` 提供完整脚手架，复制后替换 TODO 即可。

| 步骤 | 文件                                     | 操作                                                         |
| ---- | ---------------------------------------- | ------------------------------------------------------------ |
| 1    | `Server/server/games/新游戏/__init__.py` | 定义 GAME_INFO（id/name/locations/per_player/create_engine） |
| 2    | `Server/server/games/新游戏/engine.py`   | 实现 GameEngine Protocol（继承 BaseGameEngine）              |
| 3    | `Server/server/games/__init__.py`        | 添加一行 `from . import 新游戏` + `register_game()`          |
| 4    | `Client/client/games/新游戏_handler.py`  | 实现 GameClientHandler（handle_event/on_enter/on_leave）     |
| 5    | `Client/client/games/新游戏_renderer.py` | 实现 GameRenderer（render_board）                            |
| 6    | `Client/client/games/__init__.py`        | 添加一行 `from . import 新游戏_handler, 新游戏_renderer`     |
| 7    | JSON 数据文件                            | commands.json（指令）、player_data.json（默认数据）等        |

框架代码零修改。最小可用只需步骤 1-3（服务端 3 个文件），基础体验加步骤 4-6（+ 指令/渲染/事件处理），完整体验按需加 JSON 数据 + AI 感知。

### 添加新全局指令

| 步骤 | 文件                                      | 操作                                                |
| ---- | ----------------------------------------- | --------------------------------------------------- |
| 1    | `Server/server/data/commands.json`        | 在 `"*"` 中添加指令元数据                           |
| 2    | `Server/server/lobby/command_registry.py` | 实现 handler 函数 + `register_global(cmd, handler)` |

### 添加新游戏指令

| 步骤 | 文件                         | 操作                             |
| ---- | ---------------------------- | -------------------------------- |
| 1    | 游戏目录下的 `commands.json` | 在对应位置添加指令元数据         |
| 2    | 游戏引擎或独立 handlers 文件 | 实现 `cmd_X` 函数 + 添加到路由表 |

现有模板: `building_handlers.py` 的 `BUILDING_HANDLERS` 路由表模式。

### 添加新客户端面板

| 步骤 | 文件                             | 操作                                           |
| ---- | -------------------------------- | ---------------------------------------------- |
| 1    | `Client/client/panels/新面板.py` | 实现 Panel 类（继承 InputBarMixin 等）         |
| 2    | 面板文件底部                     | `register_module(name, label, class, scope)`   |
| 3    | `Client/client/state.py`         | 添加 State 类 + 在 ModuleStateManager 中实例化 |
| 4    | `Client/client/net/dispatch.py`  | 添加对应消息类型的 State 更新逻辑              |

### 添加新消息类型

| 步骤 | 文件                            | 操作                             |
| ---- | ------------------------------- | -------------------------------- |
| 1    | `Server/server/msg_types.py`    | 添加类型常量                     |
| 2    | `Client/client/net/messages.py` | 添加 dataclass + `_PARSERS` 表项 |
| 3    | `Client/client/net/dispatch.py` | 添加分发逻辑（更新 State）       |

## 现有游戏: World（开放世界）

```
Server/server/games/world/
  engine.py            — WorldEngine(MovementMixin, FollowMixin, BaseGameEngine)，路由入口
  movement.py          — MovementMixin（移动/冷却/视野/delta 广播）
  follow.py            — FollowMixin（跟随/取消跟随/队列移动）
  social.py            — SOCIAL_HANDLERS 路由表（enter/talk/map/user/addfriend/follow/unfollow）
  building_handlers.py — BUILDING_HANDLERS 路由表（buy/sell/forge/brew/rest/rumor/quest/board）
  __init__.py          — GAME_INFO 定义
  commands.json        — 建筑位置指令
  shops.json           — 商店数据
  recipes.json         — 配方数据
  player_data.json     — 玩家默认数据

Client/client/games/
  world_handler.py    — 事件处理（select_menu/dm_player/player_delta）
  world_renderer.py   — 地图渲染（瓦片→NPC→玩家三层）
```

WorldEngine 核心状态（ClassVar 共享给所有实例）:

- `_positions` / `_maps` / `_facings` / `_viewports` — 位置系统
- `_map_players` — 地图玩家索引
- `_following` / `_followers` — 跟随系统
- `_last_move` / `_cooldowns` — 冷却系统

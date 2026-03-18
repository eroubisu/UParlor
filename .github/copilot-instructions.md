# 一刀切插拔架构

本项目的**最根本设计原则**：框架与游戏模块之间通过**明确的 Protocol 接口**彻底隔离。每个模块只需实现约定的输入/输出契约，即可像插头一样插入框架运行。核心框架代码（`app.py`、`chat_server.py`、`lobby_engine.py`）**永远不因新增游戏而修改**。

一切其他原则（数据分离、SSOT、State-first 等）都服务于这个根本目标。当任何编码决策产生冲突时，**插拔隔离优先**。

## 核心原则

- **插拔隔离**：核心框架不因新增游戏而修改
- **优先复用**：功能如有成熟的第三方库已实现，优先调用而非自己造轮子，以降低项目复杂度和维护成本
- **防止冗余**：一个功能只保留一种实现方式，删除旧冗余
- **数据与代码分离**：静态数据用 JSON，不硬编码到 .py
- **SSOT**：指令来源 commands.json、颜色来源 config.py、UI 状态来源 state.py
- **State-first**：先写 State（永久），再写 Widget（临时）。业务状态只存 State，面板仅读取，禁止自行缓存副本
- **消息契约**：服务端发送与客户端解析的字段名必须精确对应，不冗余不缺漏
- **唯一色板**：`Client/client/config.py`，大厅灰度、游戏可彩色
- **文件结构**：按功能划分文件夹，保持结构清晰，避免过度嵌套

## AI 伙伴系统原则

- **选择性感知**：AI 通过 Function Calling 按需获取信息，不注入全量数据
- **三层感知**：被动摘要（自动）→ 主动工具（AI 决策）→ 事件注入（框架推送）
- **事件 opt-in**：游戏事件默认不推送给 AI，模块需主动声明优先级
- **感知不打扰**：普通事件只进入被动感知，仅重要事件触发 AI 主动搭话
- **游戏感知插拔**：框架不解读游戏数据，游戏模块通过 handler 可选方法或数据字段自行提供 AI 摘要

## 禁止事项

- ❌ 在核心框架代码中添加游戏特有逻辑
- ❌ 指令定义写在 .py 中而非 commands.json
- ❌ 游戏处理器直接访问 Widget — 必须通过 GameHandlerContext
- ❌ 游戏引擎访问框架内部属性 — 仅通过 lobby 公开方法和传入参数交互
- ❌ 面板/组件自行缓存业务状态 — 业务数据从 State 读取，纯 UI 状态（动画、渲染缓冲）除外
- ❌ 注册流程中存在游戏特定分支 — 注册函数对所有游戏一视同仁
- ❌ 元数据（名称、描述、费用等）硬编码在 .py 中 — 归 JSON 管理
- ❌ 大厅 UI 使用灰度色板外的颜色
- ❌ 任何背景颜色填充 — App/Screen/面板/组件的 background 必须为 transparent，继承终端自身背景
- ❌ 使用 Emoji（图像类 Unicode 符号如 🎆🎉👍 等）— 可使用纯文本字符（●○◆◇→←↑↓ 等）

## 架构文档

- **必读**：开始工作前先读 `ARCHITECTURE.md`，了解数据流、模块职责、Protocol 接口和扩展点地图
- **实现规范**：所有功能实现必须遵守 `.github/rules.md` 中的规范
- **规范更新**：如用户反馈或开发需要导致规范变更，必须同步更新 `.github/rules.md`

## 常见任务 → 需要读取/修改的文件

| 任务                   | 需要读取                                                    | 需要修改                                                                                                      |
| ---------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| 添加新游戏             | `ARCHITECTURE.md` "扩展点地图"                              | 服务端: `games/新游戏/`(新建) + `games/__init__.py`；客户端: `games/新handler.py`(新建) + `games/__init__.py` |
| 添加游戏指令（建筑类） | `games/world/building_handlers.py` 看模式                   | 指令 JSON + handlers 文件 + 路由表                                                                            |
| 添加游戏指令（地图类） | `games/world/engine.py` 的 handle_command                   | engine.py 的 handle_command + 指令 JSON                                                                       |
| 添加全局指令           | `lobby/command_registry.py` 看模式                          | `data/commands.json` + `command_registry.py`                                                                  |
| 添加消息类型           | `net/messages.py` + `net/dispatch.py`                       | `msg_types.py` + `messages.py`(\_PARSERS) + `dispatch.py`                                                     |
| 修改面板 UI            | 目标面板文件 + 对应 State                                   | 面板文件 + state.py(如需新状态)                                                                               |
| 修改移动/冷却          | `games/world/movement.py`                                   | movement.py                                                                                                   |
| 修改跟随系统           | `games/world/follow.py`                                     | follow.py                                                                                                     |
| 修改输入行为           | `ui/input_handler.py` + `ui/keyboard.py` + `ui/vim_mode.py` | 对应 Mixin 文件                                                                                               |
| 修改窗口布局           | `ui/layout.py` + `ui/screen.py` compose/rebuild             | layout.py                                                                                                     |
| 修改 AI 伙伴           | `ai/service.py` + `ai/attention.py`                         | 对应 ai/ 文件                                                                                                 |

## 模式参考

- **游戏指令处理器模板**：`building_handlers.py` 的 `cmd_X(lobby, player_name, player_data, args, location)` + `HANDLERS = {'cmd': func}` 路由表
- **游戏客户端处理器模板**：`world_handler.py` 的 `handle_event(event, data, ctx)` 分发 + `on_enter_game`/`on_leave_game`
- **游戏渲染器模板**：`world_renderer.py` 的 `render_board(room_data) → RenderableType`
- **全局指令模板**：`command_registry.py` 的 `_handle_X(lobby, player_name, player_data, args, location)` + `register_global()`

## rules.md 维护规则

- **定位**：rules.md 记录实现层面的统一规范（UI 样式、交互约定、AI 行为约束等），不记录架构原则
- **抽象程度**：只写规则和约束，不写具体代码片段、变量名、文件路径引用。规范应当即使文件重命名也不需要更新
- **新增规范**：当实现中确立了一种通用模式（如新组件样式、新交互约定），提炼为规则写入 rules.md
- **删除规范**：当规范对应的功能被移除或规则已过时，同步删除
- **禁止内容**：Python 代码示例、具体文件名/类名/方法名引用、硬编码色值/常量名

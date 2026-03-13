# 一刀切插拔架构

本项目的**最根本设计原则**：框架与游戏模块之间通过**明确的 Protocol 接口**彻底隔离。每个模块只需实现约定的输入/输出契约，即可像插头一样插入框架运行。核心框架代码（`app.py`、`chat_server.py`、`lobby_engine.py`）**永远不因新增游戏而修改**。

一切其他原则（数据分离、SSOT、State-first 等）都服务于这个根本目标。当任何编码决策产生冲突时，**插拔隔离优先**。

## 四个 Protocol 接口

- **GameEngine**（`Server/server/game_protocol.py`）— 服务端游戏引擎
- **GameClientHandler**（`Client/client/game_handler.py`）— 客户端事件处理器
- **GameRenderer**（`Client/client/game_renderer.py`）— 客户端游戏画面渲染器
- **GAME_INFO + commands.json** — 声明式注册（元数据 + 指令）

## 核心原则

- **插拔隔离**：核心框架不因新增游戏而修改
- **优先复用**：功能如有成熟的第三方库已实现，优先调用而非自己造轮子，以降低项目复杂度和维护成本
- **防止冗余**：一个功能只保留一种实现方式，删除旧冗余
- **数据与代码分离**：静态数据用 JSON，不硬编码到 .py
- **SSOT**：指令来源 commands.json、颜色来源 config.py、UI 状态来源 state.py
- **State-first**：先写 State（永久），再写 Widget（临时）
- **唯一色板**：`Client/client/config.py`，大厅灰度、游戏可彩色

## 禁止事项

- ❌ 在核心框架代码中添加游戏特有逻辑
- ❌ 指令定义写在 .py 中而非 commands.json
- ❌ 游戏处理器直接访问 Widget — 必须通过 GameHandlerContext
- ❌ 大厅 UI 使用灰度色板外的颜色
- ❌ 任何背景颜色填充 — App/Screen/面板/组件的 background 必须为 transparent，继承终端自身背景

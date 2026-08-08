# Rules

次要规则 — 特定场景下需要遵循。根本原则见 `copilot-instructions.md`。

---

## 1. 游戏奖励设计

奖励理念与计算基准以[游戏设计偏好](../docs/design/game-design-principles.md#rewards-and-economy)
为唯一来源。实现时数值必须存入各游戏的 `data/rewards.json`，由引擎加载，禁止硬编码。

---

## 2. 涉及玩家列表时，优先只列出好友

玩家选择范围以[选择优先交互原则](../docs/design/game-design-principles.md#selection-first-interaction)
为唯一来源。实现默认读取 `player_data.get('friends', [])`；仅管理员操作等原则明确不适用的
场景才读取全部在线玩家。

---

## 3. 更新可滚动内容时保留阅读位置

聊天、日志、旅伴等可滚动内容更新前先判断用户是否位于底部；只有原本在底部时才调用
`scroll_end(animate=False)`。禁止在用户阅读历史内容时强制跳到底部。游戏选择统一显示在
`RoomControlsPanel` 或棋盘内，不再使用旧式弹出指令栏。

---

## 4. 专项审计按需执行

日常局部修复不自动执行全仓库审计。只有用户明确要求、准备发布，或已有证据指向跨模块的重复
逻辑、死代码、State 绕过、并发或依赖风险时，才调用只读质量审计器。审计与功能修改分开，
先报告具体发现，再由用户决定是否修复。

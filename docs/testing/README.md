# UParlor manual testing

这些手册覆盖自动测试不适合证明的行为：终端渲染、键盘/IME、浮窗、多人同步、
完整对局和真实 LLM。功能改动必须更新对应手册；发布前按
[07 release checklist](07-release-checklist.md) 选择并执行用例。

## 测试环境

1. Windows Terminal 或 VS Code 集成终端，字体设置为 Nerd Font Mono v3。
2. 在仓库根目录创建 `.venv`，安装客户端与服务端测试依赖：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".\Client[test]" -e ".\Server[test]"
   ```

3. 先运行 VS Code 任务 `UParlor: Check repository`。
4. 运行 `UParlor: Start local server`。
5. 每个测试玩家分别启动一个 `UParlor: Start local client` 任务实例。
6. 只使用临时测试账号；`Server\data\` 是运行时数据，不得提交。

## 记录格式

每个执行结果记录：

```text
用例 ID:
结果: PASS / FAIL / BLOCKED
环境: OS、终端、字体、窗口尺寸、Python
证据: 脱敏截图或短日志
备注: 实际结果与复现步骤
```

证据不得包含密码、API Key、访问令牌、真实私聊内容或个人资料。失败时保留最小复现，
不要只写“有问题”。

## 手册索引

| 编号 | 范围 | 手册 |
| --- | --- | --- |
| 01 | 启动、登录、导航、断线 | [Smoke and lifecycle](01-smoke.md) |
| 02 | 中文、IME、Nerd Font、窗口尺寸 | [Terminal, Unicode, and windows](02-terminal-and-windows.md) |
| 03 | 在线、好友、频道、私聊、通知 | [Social and chat](03-social.md) |
| 04 | UNO 完整对局 | [UNO](04-uno.md) |
| 05 | 飞行棋完整对局 | [Ludo](05-ludo.md) |
| 06 | AI 旅伴与真实 LLM | [AI companion](06-companion.md) |
| 07 | 发布覆盖范围 | [Release manual checklist](07-release-checklist.md) |

## 维护规则

- 用例 ID 一经发布不得复用；删除行为时标记 retired，而不是给新行为使用旧 ID。
- 共享环境只写在本页，各手册只写额外前置条件。
- 修复人工发现的缺陷时，先补或更新能复现它的用例。
- 纯内部重构至少执行 smoke；影响哪一层，再追加对应手册。

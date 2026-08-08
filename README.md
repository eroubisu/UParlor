# UParlor — 终端游戏厅

终端里的多人在线游戏大厅。Vim 风格键盘操作。

## 安装

```
pip install uparlor
```

## 启动

```
uparlor
```

终端字体请使用 **Nerd Font Mono v3**。UParlor 的内置界面和游戏图形仅使用可由
终端前景色统一着色的单色字形，不使用自带配色的 emoji。聊天和玩家输入仍支持完整
Unicode 文本，并按 Unicode 字素簇和终端单元格宽度进行布局。

## 卸载

```
uparlor --uninstall
```

删除所有本地数据并卸载包。

## 开发

- [日常 AI 开发工作流（从这里开始）](WORKFLOW.md)
- [贡献与 AI 协作流程](CONTRIBUTING.md)
- [游戏设计偏好](docs/design/game-design-principles.md)
- [架构扩展契约](docs/architecture/extension-contracts.md)
- [人工测试手册](docs/testing/README.md)
- [质量门禁](docs/quality/README.md)

## 自建服务器

```
cd Server
pip install .
python -m server
```

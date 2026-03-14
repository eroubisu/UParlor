# UParlor — 终端游戏厅

在终端里和朋友下棋、打牌、聊天。

## 它是什么

UParlor 是一个运行在终端里的**多人在线游戏大厅**。连上服务器，登录账号，就能和其他玩家一起玩。

界面用键盘操作，支持 Vim 风格快捷键，不需要鼠标。

## 安装

```
pip install uparlor
```

## 启动

```
uparlor
```

首次运行会连接到公共服务器，注册账号后即可游玩。

## 自建服务器

```
cd Server
pip install .
python server.py [端口号]
```

客户端启动时可指定服务器地址：

```
uparlor --host 你的IP --port 端口号
```

"""旅伴 (AI Companion) 模块 — 主客户端进程内的本地 AI 聊天功能。

定位:
- 不是玩家。不连服务器，不占账号。仅在本地运行。
- 玩家通过浮窗 (CompanionWindow) 与之 1:1 对话。
- 启用时后台 tick 触发主动搭话 (通过 UI 通知)。
- AI 通过 LLM function calling 查询主客户端 State 的账号标记会话快照。

按玩家用户名隔离: ~/.uparlor/companion/players/<player>/

模块结构:
    config.py        全局/玩家级配置 + 路径
    character.py     角色定义
    persona.py       Character → system prompt
    mood/cognitive/social/impression.py    4 层心理状态
    memory.py        关键词检索式长期记忆
    attention.py     LLM function tools + 环境摘要
    provider.py      LLM Provider 抽象 (Google Gemini / OpenAI 兼容)
    service.py       AIService — 心理状态机 + 工具调用 + 内联反思
    controller.py    CompanionController 单例 — 生命周期 + 后台 tick
"""

from .controller import CompanionController
from .service import AIService
from .character import Character, CharacterSummary, list_characters

__all__ = [
    "CompanionController",
    "AIService",
    "Character", "CharacterSummary", "list_characters",
]

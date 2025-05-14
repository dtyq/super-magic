"""
定义消息传递系统中使用的类型
"""

from enum import Enum


class MessageType(str, Enum):
    """任务消息类型枚举"""
    CHAT = "chat"  # 聊天消息
    TASK_UPDATE = "task_update"  # 任务更新
    THINKING = "thinking"  # 思考过程
    INIT = "init"  # 初始化
    TOOL_CALL = "tool_call"  # 工具调用

"""
客户端消息结构定义

定义客户端发送给服务端的WebSocket消息结构
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, validator

from app.core.config.communication_config import MessageSubscriptionConfig, STSTokenRefreshConfig
from app.core.entity.message.message import MessageType
from app.core.entity.project_archive import ProjectArchiveInfo
from agentlang.environment import Environment


class ClientMessage(BaseModel):
    """任务消息模型"""
    message_id: str
    type: Union[MessageType, str]

    class Config:
        use_enum_values = True


class ContextType(str, Enum):
    """消息上下文类型枚举"""
    NORMAL = "normal"      # 正常消息
    FOLLOW_UP = "follow_up"  # 追问消息
    INTERRUPT = "interrupt"  # 中断消息

class TaskMode(str, Enum):
    """任务模式类型枚举"""
    CHAT = "chat"      # 聊天模式，使用magic.agent
    PLAN = "plan"      # 规划模式，使用super-magic.agent

class ChatClientMessage(ClientMessage):
    """
    聊天消息类型
    
    用于处理用户发送的聊天消息
    """
    type: str = MessageType.CHAT.value
    prompt: str
    attachments: List[Dict[str, Any]] = []
    context_type: ContextType = ContextType.NORMAL  # 默认为普通消息
    task_mode: TaskMode = TaskMode.PLAN  # 任务模式，默认为规划模式

    @validator('attachments', each_item=True)
    def validate_attachment(cls, v):
        if not isinstance(v, dict):
            raise ValueError("附件必须是对象")

        required_fields = ["file_tag", "filename", "file_key", "file_size", "file_url"]

        for field in required_fields:
            if field not in v:
                raise ValueError(f"附件必须包含 '{field}' 字段")

        # 验证字符串类型字段
        string_fields = ["file_tag", "filename", "file_key", "file_url"]
        for field in string_fields:
            if not isinstance(v[field], str):
                raise ValueError(f"附件的 '{field}' 必须是字符串")

        # 验证文件大小必须是整数
        if not isinstance(v["file_size"], (int, float)):
            raise ValueError("附件的 'file_size' 必须是数字类型")

        return v


class InitClientMessage(ClientMessage):
    """
    初始化消息类型
    
    用于工作区初始化
    """
    type: str = MessageType.INIT.value
    message_subscription_config: Optional[MessageSubscriptionConfig] = None  # 消息订阅配置，可选字段
    sts_token_refresh: Optional[STSTokenRefreshConfig] = None  # STS Token刷新配置，可选字段
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    upload_config: Optional[Dict[str, Any]] = None  # 上传配置，可包含平台类型和临时凭证

    @validator('message_subscription_config')
    def validate_message_subscription_config(cls, v):
        if Environment.is_dev():
            return v
        if v is None:
            raise ValueError("消息订阅配置 'message_subscription_config' 不能为空")
        return v

    @validator('metadata')
    def validate_metadata(cls, v):
        if v is None:
            raise ValueError("元数据 'metadata' 不能为空")
        return v

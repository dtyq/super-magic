

from agentlang.event.common import BaseEventData
from app.core.context.agent_context import AgentContext
from app.core.entity.message.client_message import ChatClientMessage


class AfterClientChatEventData(BaseEventData):
    """客户端聊天后的事件数据结构"""

    agent_context: AgentContext
    client_message: ChatClientMessage


class BeforeSafetyCheckEventData(BaseEventData):
    """安全检查前事件的数据结构"""

    agent_context: AgentContext
    query: str  # 需要检查的查询内容


class AfterSafetyCheckEventData(BaseEventData):
    """安全检查后事件的数据结构"""

    agent_context: AgentContext
    query: str  # 已检查的查询内容
    is_safe: bool  # 是否安全

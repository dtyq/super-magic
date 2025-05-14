"""
FinishTask 工具监听器服务

用于监听 FinishTask 工具的调用事件，当 FinishTask 工具被成功调用后，执行相应的处理逻辑
"""

from agentlang.event.data import AfterToolCallEventData
from agentlang.event.event import Event, EventType
from agentlang.logger import get_logger
from app.core.context.agent_context import AgentContext
from app.core.entity.event.event_context import EventContext
from app.service.agent_event.base_listener_service import BaseListenerService

logger = get_logger(__name__)


class FinishTaskListenerService:
    """
    FinishTask 工具监听器服务

    监听 FinishTask 工具的调用事件，在 FinishTask 工具成功调用后执行相应处理逻辑
    """

    @staticmethod
    def register_standard_listeners(agent_context: AgentContext) -> None:
        """
        为代理上下文注册 FinishTask 工具事件监听器

        Args:
            agent_context: 代理上下文对象
        """
        # 创建事件类型到处理函数的映射
        event_listeners = {
            EventType.AFTER_TOOL_CALL: FinishTaskListenerService._handle_after_tool_call
        }

        # 使用基类方法批量注册监听器
        BaseListenerService.register_listeners(agent_context, event_listeners)

        logger.info("已为代理上下文注册 FinishTask 工具事件监听器")

    @staticmethod
    async def _handle_after_tool_call(event: Event[AfterToolCallEventData]) -> None:
        """
        处理工具调用后事件，特别关注 FinishTask 工具的调用

        Args:
            event: 工具调用后事件对象，包含 AfterToolCallEventData 数据
        """
        # 检查是否为 FinishTask 工具调用
        if event.data.tool_name != "finish_task":
            return

        # 获取工具调用的输出消息
        message = event.data.result.content

        # 检查工具调用是否成功（没有错误）
        if not event.data.result.ok:
            logger.warning(f"FinishTask 工具调用失败: {message}")
            return

        logger.info("监测到 FinishTask 工具成功调用")

        # 在事件上下文中设置finish_task_called标记为True
        event_context = event.data.tool_context.get_extension_typed("event_context", EventContext)
        if event_context:
            event_context.finish_task_called = True
            logger.info(f"任务已完成，最终消息: {message}")
        else:
            logger.warning("无法设置finish_task_called标记：EventContext未注册")

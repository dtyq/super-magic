import os
from typing import Generic, TypeVar

from agentlang.context.tool_context import ToolContext
from agentlang.event.event import EventType
from agentlang.logger import get_logger
from app.core.context.agent_context import AgentContext
from app.core.entity.event.file_event import FileEventData
from app.core.entity.message.server_message import DisplayType
from app.tools.core.base_tool import BaseTool
from app.tools.core.base_tool_params import BaseToolParams

logger = get_logger(__name__)

# 定义参数类型变量
T = TypeVar('T', bound=BaseToolParams)


class AbstractFileTool(BaseTool[T], Generic[T]):
    """
    抽象文件工具基类

    为文件操作工具提供通用的文件事件分发功能
    """

    async def _dispatch_file_event(self, tool_context: ToolContext, filepath: str, event_type: EventType, is_screenshot: bool = False) -> None:
        """
        分发文件事件

        Args:
            tool_context: 工具上下文
            filepath: 文件路径
            event_type: 事件类型（FILE_CREATED, FILE_UPDATED 或 FILE_DELETED）
        """
        # 创建事件数据，包含 tool_context
        event_data = FileEventData(
            filepath=filepath,
            event_type=event_type,
            tool_context=tool_context,
            is_screenshot=is_screenshot
        )

        try:
            agent_context = tool_context.get_extension_typed("agent_context", AgentContext)
            if agent_context:
                await agent_context.dispatch_event(event_type, event_data)
                logger.info(f"已分发文件事件: {event_type} - {filepath}")
            else:
                logger.error("未从 ToolContext 中找到 AgentContext 扩展")
        except Exception as e:
            # 打印调用栈信息以便于调试
            import traceback
            stack_trace = traceback.format_exc()
            logger.error(f"分发文件事件失败: {e}，调用栈信息:\n{stack_trace}")

    def get_display_type_by_extension(self, file_path: str) -> DisplayType:
        """
        根据文件扩展名获取适当的 DisplayType

        Args:
            file_path: 文件路径

        Returns:
            DisplayType: 展示类型
        """
        file_name = os.path.basename(file_path)
        file_extension = os.path.splitext(file_name)[1].lower()

        display_type = DisplayType.TEXT
        if file_extension in ['.md', '.markdown']:
            display_type = DisplayType.MD
        elif file_extension in ['.html', '.htm']:
            display_type = DisplayType.HTML
        elif file_extension in ['.php', '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.hpp', '.json', '.yaml', '.yml', '.toml', '.ini', '.sh']:
            display_type = DisplayType.CODE

        return display_type

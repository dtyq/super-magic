"""
向用户提问工具，用于向用户提出问题并等待用户回复

此工具使Assistant能够向用户请求更多信息或确认
"""


from typing import Any, Dict, Optional

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from app.core.entity.message.server_message import AskUserContent, DisplayType, ToolDetail
from app.core.entity.tool.tool_result import AskUserToolResult
from app.tools.core import BaseTool, BaseToolParams, tool

logger = get_logger(__name__)

_ASK_USER_DESCRIPTION = """当需要向用户请求额外信息、确认或进一步指示时使用此工具。
它允许你提出问题并等待用户的回复，然后再继续，仅在必要时使用，通常情况下你应该自主决定流程的走向以解决用户的问题和目标。"""


class AskUserParams(BaseToolParams):
    """向用户提问参数"""
    question: str = Field(
        ...,
        description="要向用户提出的问题或请求"
    )
    type: Optional[str] = Field(
        None,
        description="可选的内容类型，例如 'todo'"
    )
    content: Optional[str] = Field(
        None,
        description="与问题相关的内容，例如任务内容、代码片段等"
    )


@tool()
class AskUser(BaseTool[AskUserParams]):
    """
    向用户提问工具

    当需要向用户请求额外信息、确认或进一步指示时使用此工具。
    它允许你提出问题并等待用户的回复，然后再继续，仅在必要时使用，通常情况下你应该自主决定流程的走向以解决用户的问题和目标。
    """

    async def execute(self, tool_context: ToolContext, params: AskUserParams) -> AskUserToolResult:
        """
        向用户提出问题并等待回复

        Args:
            tool_context: 工具上下文
            params: 参数对象，包含问题内容和可选的类型及内容

        Returns:
            AskUserToolResult: 包含提问信息的工具结果
        """
        logger.info(f"向用户提问: {params.question}")
        if params.type:
            logger.info(f"内容类型: {params.type}")
        if params.content:
            logger.info(f"相关内容: {params.content}")

        # 创建AskUserToolResult实例，直接设置各个字段
        result = AskUserToolResult(
            question=params.question,
            content=params.question,  # 使用问题内容作为 ToolResult 的 content 字段的默认值
            system="ASK_USER",  # 系统指令，标记这是一个用户问询
        )

        # 设置可选字段
        if params.type:
            result.set_type(params.type)
        if params.content:
            result.set_content(params.content)

        return result

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """
        获取工具调用后的友好动作和备注

        Args:
            tool_name: 工具名称
            tool_context: 工具上下文
            result: 工具执行结果
            execution_time: 执行耗时
            arguments: 执行参数

        Returns:
            Dict: 包含action和remark的字典
        """
        question = ""
        if arguments and "question" in arguments:
            question = arguments["question"]

        return {
            "action": "",  # 按照模板要求设为空字符串
            "remark": ""  # 使用工具的question内容作为备注
        }

    async def get_after_tool_call_friendly_content(self, tool_context: ToolContext, result: AskUserToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> str:
        """
        获取工具调用后的友好内容

        Args:
            tool_context: 工具上下文
            result: 工具执行结果 (实际上是 AskUserToolResult 类型)
            execution_time: 执行耗时
            arguments: 执行参数

        Returns:
            str: 友好的执行结果消息
        """
        # 直接使用 result 的 question 属性，无需类型检查
        ask_result = result  # type: AskUserToolResult
        return f"正在等待用户回复问题: {ask_result.question}"

    async def get_tool_detail(self, tool_context: ToolContext, result: AskUserToolResult, arguments: Dict[str, Any] = None) -> Optional[ToolDetail]:
        """
        根据工具执行结果获取对应的ToolDetail

        Args:
            tool_context: 工具上下文
            result: 工具执行的结果 (实际上是 AskUserToolResult 类型)
            arguments: 工具执行的参数字典

        Returns:
            Optional[ToolDetail]: 工具详情对象
        """
        if not result.ok:
            return None

        # 直接使用 AskUserToolResult 的属性
        ask_result = result  # type: AskUserToolResult

        # 优先使用 result.content，如果为空则使用 question
        content = ask_result.content or ask_result.question

        # 获取问题类型（如果有）
        question_type = getattr(ask_result, 'type', None)

        # 创建自定义的工具详情
        return ToolDetail(
            type=DisplayType.ASK_USER,
            data=AskUserContent(
                content=content,
                question_type=question_type
            )
        )

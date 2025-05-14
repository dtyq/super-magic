from typing import Any, Dict, List

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from agentlang.tools.tool_result import ToolResult
from app.tools.core import BaseTool, BaseToolParams, tool


class FinishTaskParams(BaseToolParams):
    """完成任务参数"""
    explanation: str = Field(
        "",  # 虽然有默认值，但在实际调用时会被处理为必填字段
        description="""
        请以第一人称（使用"我"）总结你已经完成的工作，重点描述：
        1. 你完成了哪些主要任务
        2. 生成了哪些交付物（文件、报告等）
        3. 这些交付物解决了用户什么问题或满足了什么需求
        请不要提及"完成任务"工具本身，只需要描述工作成果和价值。
        """
    )
    message: str = Field(
        ...,
        description="在完成任务前向用户提供的最终消息，不要和 explanation 重复，是比 explanation 更进一步的总结语。"
    )
    files: List[str] = Field(
        ...,
        description="与最终消息相关的文件路径列表，如：['final_report.md', 'final_report.html', '.webview_report/xxx.md']"
    )


@tool()
class FinishTask(BaseTool[FinishTaskParams]):
    """
    当您完成了所有必需的任务并想要提供最终回复时，应调用此工具。调用此工具后，当前会话轮次将结束，因此请确保在调用此工具之前已完成当前轮次任务的所有必要操作。
    """

    async def execute(self, tool_context: ToolContext, params: FinishTaskParams) -> ToolResult:
        """完成当前任务并提供最终消息"""
        # 将文件列表格式化并追加到消息中
        files_str = ""
        if params.files and len(params.files) > 0:
            files_str = "\n\n关联文件：\n" + "\n".join([f"- {file}" for file in params.files])

        # 合并消息和文件列表
        final_content = params.explanation + "\n\n" + params.message + files_str

        return ToolResult(
            content=final_content,
            system="FINISH_TASK",  # 系统指令，用于标记任务完成
        )

    async def get_after_tool_call_friendly_content(
        self,
        tool_context: ToolContext,
        result: ToolResult, # 此工具的 execute 方法返回的 ToolResult
        execution_time: float,
        arguments: Dict[str, Any] # 调用此工具时的参数，即 FinishTaskParams 的内容
    ) -> str:
        """为 finish_task 工具提供最终的用户友好消息。
        在这种设计下，我们直接返回 execute 方法准备好的 result.content。
        """
        if result and result.get_content() is not None:
            return result.get_content() # No .strip()
        return "" # Fallback to empty string

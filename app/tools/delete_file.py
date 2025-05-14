import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import Field

from agentlang.utils.file import safe_delete
from agentlang.context.tool_context import ToolContext
from app.core.entity.message.server_message import ToolDetail
from agentlang.tools.tool_result import ToolResult
from agentlang.event.event import EventType
from agentlang.logger import get_logger
from app.tools.abstract_file_tool import AbstractFileTool
from app.tools.core import BaseToolParams, tool
from app.tools.workspace_guard_tool import WorkspaceGuardTool

logger = get_logger(__name__)


class DeleteFileParams(BaseToolParams):
    """删除文件参数"""
    file_path: str = Field(
        ...,
        description="要删除的文件路径"
    )


@tool()
class DeleteFile(AbstractFileTool[DeleteFileParams], WorkspaceGuardTool[DeleteFileParams]):
    """
    删除文件工具，用于删除指定的文件。

    注意：
    - 删除前请确认文件路径正确。
    - 如果文件不存在将返回错误。
    - 建议在删除重要文件前先备份。
    - 只能删除工作目录中的文件
    """

    def __init__(self, **data):
        super().__init__(**data)

    async def execute(self, tool_context: ToolContext, params: DeleteFileParams) -> ToolResult:
        """
        执行文件删除操作

        Args:
            tool_context: 工具上下文
            params: 参数对象，包含文件路径

        Returns:
            ToolResult: 包含操作结果
        """
        try:
            # 使用基类方法获取安全文件路径
            file_path, error = self.get_safe_path(params.file_path)
            if error:
                return ToolResult(error=error)

            # 检查文件是否存在
            if not file_path.exists():
                return ToolResult(error=f"文件不存在: {file_path}")

            # 记录文件路径用于后续触发事件
            file_path_str = str(file_path)

            # 使用 safe_delete 函数处理删除逻辑
            await safe_delete(file_path)
            logger.info(f"已成功请求删除路径: {file_path}") # safe_delete 内部会记录具体方式

            # 触发文件删除事件
            await self._dispatch_file_event(tool_context, file_path_str, EventType.FILE_DELETED)

            # 返回成功结果
            return ToolResult(content=f"文件已成功删除\nfile_path: {file_path!s}")

        except Exception as e:
            logger.exception(f"删除文件失败: {e!s}")
            return ToolResult(error=f"删除文件失败: {e!s}")

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """
        获取工具调用后的友好动作和备注
        """
        file_path = arguments.get("file_path", "") if arguments else ""
        return {
            "action": "删除文件",
            "remark": file_path
        }

import os
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional

import aiofiles
from pydantic import Field

from agentlang.context.tool_context import ToolContext
from app.core.entity.message.server_message import DisplayType, FileContent, ToolDetail
from agentlang.tools.tool_result import ToolResult
from agentlang.event.event import EventType
from agentlang.logger import get_logger
from app.tools.abstract_file_tool import AbstractFileTool
from app.tools.core import BaseToolParams, tool
from app.tools.workspace_guard_tool import WorkspaceGuardTool
from agentlang.utils.syntax_checker import SyntaxChecker

logger = get_logger(__name__)


class WriteToFileParams(BaseToolParams):
    """写入文件参数"""
    file_path: str = Field(
        ...,
        description="要写入的文件路径，相对于工作目录或绝对路径，不要包含工作目录，比如希望将文件写到 .workspace/todo.md，只需要传入 todo.md 即可"
    )
    content: str = Field(
        ...,
        description="要写入文件的完整内容"
    )
    overwrite: bool = Field(
        False,
        description="是否允许覆盖已存在的文件。默认为 false，不允许覆盖。"
    )

    @classmethod
    def get_custom_error_message(cls, field_name: str, error_type: str) -> Optional[str]:
        """获取自定义参数错误信息"""
        if field_name == "content":
            error_message = (
                "缺少必要参数'content'。这可能是因为您提供的内容过长，超出了token限制。\n"
                "建议：\n"
                "1. 减少输出内容的量，分批次完成文件内容\n"
                "2. 将大文件拆分为多个小文件\n"
                "3. 确保在调用时明确提供content参数"
            )
            return error_message
        return None


class WriteResult(NamedTuple):
    """写入结果详情"""
    content: str  # 写入的内容
    file_exists: bool  # 文件是否已存在
    total_lines: int  # 总行数
    file_size: int  # 文件大小（字节）
    has_syntax_errors: bool  # 是否有语法错误
    syntax_errors: list  # 语法错误列表


@tool()
class WriteToFile(AbstractFileTool[WriteToFileParams], WorkspaceGuardTool[WriteToFileParams]):
    """
    写入文件工具

    这个工具可以将内容写入到指定路径的文件中，如果文件不存在会创建文件。

    - 如果文件不存在，将自动创建文件和必要的目录。
    - 如果文件已存在，默认行为是返回错误。要覆盖现有文件，请将 overwrite 参数设置为 true。
    - 减少单次输出内容的量，建议分批次完成文件内容，先调用 write_to_file 写入新文件，再调用 replace_in_file 来修改追加文件内容。
    - 如果需要复制或移动文件，请使用 shell_exec 工具来执行 cp 或 mv 命令。
    - 如果需要对现有文件进行局部修改，请务必使用 replace_in_file 工具。
    """

    async def execute(self, tool_context: ToolContext, params: WriteToFileParams) -> ToolResult:
        """
        执行文件写入操作

        Args:
            tool_context: 工具上下文
            params: 参数对象，包含文件路径、内容和覆盖选项

        Returns:
            ToolResult: 包含操作结果
        """
        try:
            # 使用父类方法获取安全的文件路径
            file_path, error = self.get_safe_path(params.file_path)
            if error:
                return ToolResult(error=error)

            # 检查文件是否存在
            file_exists = file_path.exists()

            # 如果文件已存在且不允许覆盖
            if file_exists and not params.overwrite:
                return ToolResult(
                    error=f"文件 {file_path!s} 已存在。如需覆盖，请在参数中设置 `overwrite=true`。"
                )

            # 创建目录（如果需要）
            await self._create_directories(file_path)

            # 写入文件内容
            await self._write_file(file_path, params.content)

            # 触发文件事件
            event_type = EventType.FILE_UPDATED if file_exists else EventType.FILE_CREATED
            await self._dispatch_file_event(tool_context, str(file_path), event_type)

            # 执行语法检查
            valid, errors = SyntaxChecker.check_syntax(str(file_path), params.content)

            # 计算文件统计信息
            write_result = self._calculate_write_stats(
                params.content,
                file_exists, # 传递原始的文件存在状态
                not valid,
                errors
            )

            # 生成格式化的输出
            action_verb = "文件覆盖" if file_exists else "文件创建"
            output = (
                f"{action_verb}: {file_path} | "
                f"{write_result.total_lines}行 | "
                f"大小:{write_result.file_size}字节"
            )

            # 如果有语法错误，添加到结果中
            if not valid:
                errors_str = "\n".join(errors)
                output += f"\n\n警告：文件存在语法问题：\n{errors_str}"
                logger.warning(f"文件 {file_path} 存在语法问题: {errors}")

            # 返回操作结果
            return ToolResult(content=output)

        except Exception as e:
            logger.exception(f"写入文件失败: {e!s}")
            return ToolResult(error=f"写入文件失败: {e!s}。这可能是因为您提供的内容过长，超出了token限制。\n"
                "建议：\n"
                "1. 减少输出内容的量，分批次追加文件内容\n"
                "2. 将大内容拆分为多次追加操作\n"
                "3. 确保在调用时明确提供content参数")

    async def _create_directories(self, file_path: Path) -> None:
        """创建文件所需的目录结构"""
        directory = file_path.parent

        if not directory.exists():
            os.makedirs(directory, exist_ok=True)
            logger.info(f"创建目录: {directory}")

    async def _write_file(self, file_path: Path, content: str) -> None:
        """写入文件内容"""
        # 处理内容末尾可能的空行
        if not content.endswith("\n"):
            content += "\n"

        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(content)

        logger.info(f"文件写入完成: {file_path}")

    async def get_tool_detail(self, tool_context: ToolContext, result: ToolResult, arguments: Dict[str, Any] = None) -> Optional[ToolDetail]:
        """
        根据工具执行结果获取对应的ToolDetail

        Args:
            tool_context: 工具上下文
            result: 工具执行的结果
            arguments: 工具执行的参数字典

        Returns:
            Optional[ToolDetail]: 工具详情对象，可能为None
        """
        if not result.ok:
            return None

        if not arguments or "file_path" not in arguments or "content" not in arguments:
            logger.warning("没有提供file_path或content参数")
            return None

        file_path = arguments["file_path"]
        content = arguments["content"]
        file_name = os.path.basename(file_path)

        # 使用 AbstractFileTool 的方法获取显示类型
        display_type = self.get_display_type_by_extension(file_path)

        return ToolDetail(
            type=display_type,
            data=FileContent(
                file_name=file_name,
                content=content
            )
        )

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """
        获取工具调用后的友好动作和备注
        """
        if not arguments or "file_path" not in arguments:
            return {
                "action": "写入文件",
                "remark": "写入异常，重新尝试"
            }

        file_path = arguments["file_path"]
        file_name = os.path.basename(file_path)

        # 判断是创建还是覆盖
        # 这里我们无法直接访问 file_exists 变量，但可以通过参数来推断
        # 如果调用成功，并且 overwrite=True 或者文件原本不存在，则操作成功
        # 我们可以根据 result.content 来判断，但这不够健壮
        # 一个更可靠（但非完美）的方法是检查 ToolResult 的内容是否包含"覆盖"字样
        # 或者，我们可以考虑在 execute 成功时将操作类型（创建/覆盖）放入 ToolResult 的 metadata 或直接修改 content
        # 为了简单起见，我们暂时通过参数和 ToolResult 的内容推断
        action = "创建并写入文件"
        if result.ok and result.content:
            # 检查 ToolResult 的输出信息判断是创建还是覆盖
            if "文件覆盖:" in result.content:
                action = "覆盖文件"
            elif "文件创建:" in result.content:
                action = "创建并写入文件"

        # 更准确的方式是在 execute 方法中确定操作类型并传递
        # 但目前我们依赖 result.content

        return {
            "action": action,
            "remark": file_name
        }

    def _calculate_write_stats(self, content: str, file_exists: bool, has_syntax_errors: bool, syntax_errors: list) -> WriteResult:
        """
        计算写入操作的统计信息

        Args:
            content: 写入的内容
            file_exists: 文件是否已存在
            has_syntax_errors: 是否有语法错误
            syntax_errors: 语法错误列表

        Returns:
            WriteResult: 包含写入统计信息的结果对象
        """
        # 确保内容以换行符结束
        normalized_content = content
        if not normalized_content.endswith("\n"):
            normalized_content += "\n"

        # 计算行数
        total_lines = normalized_content.count('\n') + (0 if normalized_content.endswith('\n') or not normalized_content else 1)

        # 计算文件大小
        file_size = len(normalized_content.encode('utf-8'))

        return WriteResult(
            content=content,
            file_exists=file_exists,
            total_lines=total_lines,
            file_size=file_size,
            has_syntax_errors=has_syntax_errors,
            syntax_errors=syntax_errors
        )

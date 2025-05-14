from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agentlang.context.tool_context import ToolContext
from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from agentlang.utils.token_estimator import num_tokens_from_string
from app.core.entity.message.server_message import DisplayType, FileContent, ToolDetail
from app.tools.core import BaseToolParams, tool
from app.tools.read_file import ReadFile, ReadFileParams
from app.tools.workspace_guard_tool import WorkspaceGuardTool

logger = get_logger(__name__)

# 设置最大Token限制
MAX_TOTAL_TOKENS = 30000

class ReadFilesParams(BaseToolParams):
    """批量读取文件参数"""
    files: List[str] = Field(..., description="要读取的文件路径列表，相对于工作目录或绝对路径")
    offset: int = Field(0, description="开始读取的行号（从0开始），适用于所有文件")
    limit: int = Field(200, description="要读取的行数或页数，默认200行，如果要读取整个文件，请设置为-1")


class FileReadingResult(BaseModel):
    """单个文件的读取结果"""
    file_path: str
    content: str  # 完整内容（包含元信息）
    is_success: bool
    error_message: Optional[str] = None
    tokens: int = 0  # token数量，用于计算截断


@tool()
class ReadFiles(WorkspaceGuardTool[ReadFilesParams]):
    """
    批量读取文件内容工具

    这个工具可以一次性读取多个指定路径的文件内容，所有文件使用相同的读取参数。
    支持的文件类型与 ReadFile 工具相同，包括文本文件、PDF和DOCX等格式。

    支持的文件类型：
    - 文本文件（.txt、.md、.py、.js等）
    - PDF文件（.pdf）
    - Word文档（.docx）
    - Jupyter Notebook（.ipynb）
    - Excel文件（.xls、.xlsx）
    - CSV文件（.csv）

    注意：
    - 读取工作目录外的文件被禁止
    - 二进制文件可能无法正确读取
    - 过大的文件将被拒绝读取，你必须分段读取部分内容来理解文件概要
    - 对于Excel和CSV文件，建议使用代码处理数据而不是直接使用文本内容
    - 为避免内容过长，总token数超过30000时会自动截断内容
    """

    async def execute(self, tool_context: ToolContext, params: ReadFilesParams) -> ToolResult:
        """
        执行批量文件读取操作

        Args:
            tool_context: 工具上下文
            params: 批量文件读取参数

        Returns:
            ToolResult: 包含批量文件内容或错误信息
        """
        if not params.files:
            return ToolResult(error="没有指定要读取的文件")

        results = []
        read_file_tool = ReadFile()
        read_failure_count = 0
        has_truncation = False

        # 批量处理每个文件，收集结果
        for filepath in params.files:
            try:
                # 构造单文件读取参数
                file_params = ReadFileParams(
                    file_path=filepath,
                    offset=params.offset,
                    limit=params.limit,
                    explanation=params.explanation if hasattr(params, 'explanation') else ""
                )

                # 调用 ReadFile 工具读取单个文件
                result = await read_file_tool.execute(tool_context, file_params)

                if result.ok:
                    # 直接使用 ReadFile 返回的完整内容（包含元信息）
                    content = result.content
                    tokens = num_tokens_from_string(content)

                    # 创建文件读取结果对象
                    file_result = FileReadingResult(
                        file_path=filepath,
                        content=content,
                        is_success=True,
                        tokens=tokens
                    )

                    results.append(file_result)
                else:
                    results.append(FileReadingResult(
                        file_path=filepath,
                        content="",
                        is_success=False,
                        error_message=result.content,  # 失败时，content 实际是错误信息
                        tokens=0
                    ))
                    read_failure_count += 1
            except Exception as e:
                logger.exception(f"读取文件失败: {e!s}")
                results.append(FileReadingResult(
                    file_path=filepath,
                    content="",
                    is_success=False,
                    error_message=f"读取文件异常: {e!s}",
                    tokens=0
                ))
                read_failure_count += 1

        # 检查是否需要截断内容以符合token限制
        total_content_tokens = sum(result.tokens for result in results if result.is_success)

        # 为摘要预留token
        header_tokens = 500  # 为头部预留的token
        available_tokens = MAX_TOTAL_TOKENS - header_tokens

        # 如果内容token数超出限制，进行截断
        if total_content_tokens > available_tokens:
            has_truncation = True
            logger.info(f"内容总token数({total_content_tokens})超出限制({available_tokens})，进行截断")
            results = self._truncate_contents(results, available_tokens)

        # 生成摘要信息
        total_files = len(params.files)
        success_count = total_files - read_failure_count
        truncation_info = "，内容已截断" if has_truncation else ""
        summary = f"共读取 {total_files} 个文件，成功: {success_count}，失败: {read_failure_count}{truncation_info}"

        # 格式化最终结果
        formatted_result = self._format_results(results, summary, has_truncation)

        # 记录实际token数
        actual_tokens = num_tokens_from_string(formatted_result)
        logger.info(f"最终输出token数: {actual_tokens}")

        return ToolResult(
            content=formatted_result,
            system=summary
        )

    def _truncate_contents(self, results: List[FileReadingResult], available_tokens: int) -> List[FileReadingResult]:
        """
        按比例截断内容以符合token限制

        Args:
            results: 文件读取结果列表
            available_tokens: 可用的token数

        Returns:
            截断后的结果列表
        """
        successful_files = [r for r in results if r.is_success]

        if not successful_files:
            return results

        # 计算需要截断的总token数
        total_tokens = sum(r.tokens for r in successful_files)
        ratio = available_tokens / total_tokens

        # 按比例分配token
        for result in successful_files:
            allocated_tokens = max(300, int(result.tokens * ratio))  # 确保每个文件至少有一些内容
            if result.tokens > allocated_tokens:
                # 尝试仅保留文件开头（包括元信息和部分内容）
                content = result.content

                # 通过二分查找找到合适的截断点
                left, right = 0, len(content)
                best_content = ""
                best_tokens = 0

                while left <= right:
                    mid = (left + right) // 2
                    truncated = content[:mid]
                    tokens = num_tokens_from_string(truncated)

                    if tokens <= allocated_tokens:
                        best_content = truncated
                        best_tokens = tokens
                        left = mid + 1
                    else:
                        right = mid - 1

                # 更新结果
                result.content = best_content + "\n\n[内容已截断...]"
                result.tokens = best_tokens + 10  # 为截断提示增加一些token

        return results

    def _format_results(self, results: List[FileReadingResult], summary: str, has_truncation: bool) -> str:
        """
        格式化多个文件的读取结果

        Args:
            results: 文件读取结果列表
            summary: 摘要信息
            has_truncation: 是否有内容被截断

        Returns:
            格式化后的结果文本
        """
        formatted_parts = []

        # 添加摘要信息
        formatted_parts.append(f"# 批量读取文件结果\n\n**{summary}**\n")

        if has_truncation:
            formatted_parts.append(f"> **注意**：由于内容过长（超过{MAX_TOTAL_TOKENS}token），部分文件内容已被截断。\n")

        # 添加分隔线
        formatted_parts.append("-" * 80 + "\n")

        # 添加每个文件的结果
        for idx, result in enumerate(results):
            # 添加文件分隔符（除了第一个文件）
            if idx > 0:
                formatted_parts.append("\n" + "=" * 80 + "\n")

            if result.is_success:
                # 直接使用ReadFile生成的内容（已包含元信息）
                formatted_parts.append(result.content)
            else:
                # 对失败的文件添加错误信息
                formatted_parts.append(f"## 文件: {result.file_path}\n\n读取失败: {result.error_message}\n")

        return "\n".join(formatted_parts)

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

        if not arguments or "files" not in arguments:
            logger.warning("没有提供files参数")
            return None

        file_count = len(arguments["files"])

        return ToolDetail(
            type=DisplayType.MD,
            data=FileContent(
                file_name=f"批量读取文件 (共{file_count}个文件)",
                content=result.content
            )
        )

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """
        获取工具调用后的友好动作和备注
        """
        if not arguments or "files" not in arguments:
            return {
                "action": "批量读取文件",
                "remark": "读取多个文件失败"
            }

        file_count = len(arguments["files"])

        if not result.ok:
            return {
                "action": "批量读取文件",
                "remark": f"批量读取{file_count}个文件失败"
            }

        return {
            "action": "批量读取文件",
            "remark": f"已读取{file_count}个文件"
        }

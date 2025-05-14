import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from agentlang.tools.tool_result import ToolResult
from agentlang.logger import get_logger
from agentlang.utils.schema import FileInfo
from app.tools.core import BaseToolParams, tool
from app.tools.workspace_guard_tool import WorkspaceGuardTool

logger = get_logger(__name__)


class GrepSearchParams(BaseToolParams):
    """搜索参数"""
    query: str = Field(..., description="要搜索的正则表达式模式")
    case_sensitive: bool = Field(
        False,
        description="搜索是否区分大小写"
    )
    include_pattern: str = Field(
        "",
        description="要包含的文件的Glob模式（例如，TypeScript文件的'*.ts'）"
    )
    exclude_pattern: str = Field(
        "",
        description="要排除的文件的Glob模式"
    )


@tool()
class GrepSearch(WorkspaceGuardTool[GrepSearchParams]):
    """
    基于文本的正则表达式搜索，可以在文件或目录中找到确切的模式匹配，利用ripgrep命令进行高效搜索。
    结果将以ripgrep风格格式化，可配置为包含行号和内容。
    为避免过多输出，结果上限为50个匹配项。

    这最适合查找确切的文本匹配或正则表达式模式。
    比语义搜索更精确，用于查找特定字符串或模式。
    """

    async def execute(self, tool_context: ToolContext, params: GrepSearchParams) -> ToolResult:
        """执行工具并返回结果

        Args:
            tool_context: 工具上下文
            params: 搜索参数

        Returns:
            ToolResult: 包含搜索结果或错误信息
        """
        # 调用内部方法获取结果
        result = self._run(
            query=params.query,
            case_sensitive=params.case_sensitive,
            include_pattern=params.include_pattern,
            exclude_pattern=params.exclude_pattern
        )

        # 返回ToolResult
        return ToolResult(content=result)

    def _run(self, query: str, case_sensitive: Optional[bool] = None,
             include_pattern: Optional[str] = None,
             exclude_pattern: Optional[str] = None) -> str:
        """运行工具并返回搜索结果"""
        try:
            # 构建 ripgrep 命令
            cmd = ["rg", "--line-number", "--max-count", "50", "--json"]

            # 添加大小写敏感选项
            if case_sensitive is not None:
                if not case_sensitive:
                    cmd.append("--ignore-case")

            # 添加包含模式
            if include_pattern:
                cmd.extend(["--glob", include_pattern])

            # 添加排除模式
            if exclude_pattern:
                cmd.extend(["--glob", f"!{exclude_pattern}"])

            # 添加搜索模式和目录
            cmd.extend([query, str(self.base_dir)])

            # 执行命令
            process = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.base_dir))

            # 处理结果
            if process.returncode == 0 or process.returncode == 1:  # 1 表示没有匹配
                output = process.stdout.strip()
                if not output:
                    return "未找到匹配项"

                # 解析 JSON 输出并按文件分组
                matches = self._parse_ripgrep_output(output)
                if not matches:
                    return "未找到匹配项"

                # 格式化输出
                return self._format_matches(matches)
            else:
                error_msg = process.stderr.strip()
                logger.error(f"ripgrep 搜索失败: {error_msg}")
                return f"搜索执行失败: {error_msg}"

        except FileNotFoundError:
            return "错误：未找到 ripgrep (rg) 命令。请确保已安装 ripgrep。"
        except Exception as e:
            logger.error(f"执行搜索时出错: {e}", exc_info=True)
            return f"执行搜索时出错: {e!s}"

    def _parse_ripgrep_output(self, output: str) -> Dict[Path, List[Tuple[int, str]]]:
        """解析 ripgrep 的 JSON 输出"""
        import json

        matches = {}
        for line in output.splitlines():
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    path = Path(data["data"]["path"]["text"])
                    line_number = data["data"]["line_number"]
                    content = data["data"]["lines"]["text"].strip()

                    if path not in matches:
                        matches[path] = []
                    matches[path].append((line_number, content))
            except json.JSONDecodeError:
                continue
            except KeyError:
                continue

        return matches

    def _format_matches(self, matches: Dict[Path, List[Tuple[int, str]]]) -> str:
        """格式化匹配结果"""
        output = []
        for file_path, lines in matches.items():
            # 获取文件信息
            stat = file_path.stat()
            rel_path = str(file_path.relative_to(self.base_dir))

            # 创建 FileInfo 对象
            file_info = FileInfo(
                name=file_path.name,
                path=rel_path,
                is_dir=False,
                size=stat.st_size,
                last_modified=stat.st_mtime,
                line_count=self._count_lines(file_path)
                if file_path.suffix in [".py", ".js", ".ts", ".jsx", ".tsx", ".vue", ".md", ".txt"]
                else None,
            )

            # 添加文件信息
            size_str = self._format_size(file_info.size)
            line_str = f", {file_info.line_count} lines" if file_info.line_count is not None else ""
            output.append(f"\n{file_info.path} ({size_str}{line_str}) - {file_info.format_time()}")

            # 添加匹配行
            for line_number, content in lines:
                output.append(f"  {line_number}: {content}")

        if not output:
            return "未找到匹配项"

        return "\n".join(output)

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"

    def _count_lines(self, file_path: Path) -> Optional[int]:
        """计算文件行数"""
        try:
            with file_path.open("r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        except:
            return None

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
        query = ""
        if arguments and "query" in arguments:
            query = arguments["query"]

        return {
            "action": "本地搜索文件",
            "remark": query
        }

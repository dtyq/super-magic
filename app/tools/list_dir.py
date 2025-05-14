from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from agentlang.tools.tool_result import ToolResult
from agentlang.logger import get_logger
from agentlang.utils.schema import DirectoryInfo, FileInfo
from app.tools.core import BaseToolParams, tool
from app.tools.workspace_guard_tool import WorkspaceGuardTool
from agentlang.utils.file import (
    is_text_file, format_file_size,
    count_file_lines, count_file_tokens
)

logger = get_logger(__name__)


class ListDirParams(BaseToolParams):
    """列出目录参数"""
    relative_workspace_path: str = Field(
        ".",
        description="相对于工作区根目录要列出内容的路径。"
    )
    level: int = Field(
        3,
        description="要列出的目录层级深度，默认为3。"
    )
    filter_binary: bool = Field(
        False,
        description="是否过滤二进制文件，如图片、视频等，只显示文本/代码文件"
    )


@tool()
class ListDir(WorkspaceGuardTool[ListDirParams]):
    """
    列出目录内容的工具，建议使用 level=3 来获取足够多的文件信息。

    列出目录的内容，支持指定递归层级。在使用更有针对性的工具（如语义搜索或文件读取）之前，
    这是用于发现的快速工具。在深入研究特定文件之前，尝试了解文件结构非常有用。可用于探索工作区、项目结构、文件分布等。

    对于文本文件，会显示文件大小、行数和token数量，便于评估内容量。
    """

    async def execute(self, tool_context: ToolContext, params: ListDirParams) -> ToolResult:
        """执行工具并返回结果

        Args:
            tool_context: 工具上下文
            params: 目录列表参数

        Returns:
            ToolResult: 包含目录内容或错误信息
        """
        # 验证 level 的合理性，例如限制最大深度
        max_level = 10  # 设定一个最大递归深度防止滥用
        level = params.level
        if level > max_level:
            logger.warning(f"Requested level {level} exceeds maximum {max_level}, limiting to {max_level}.")
            level = max_level
        elif level < 1:
             logger.warning(f"Requested level {level} is less than 1, setting to 1.")
             level = 1

        # 调用内部方法获取结果
        result = self._run(
            relative_workspace_path=params.relative_workspace_path,
            level=level,
            filter_binary=params.filter_binary,
            calculate_tokens=True,
        )

        # 返回ToolResult
        return ToolResult(content=result)

    def _run(self, relative_workspace_path: str, level: int, filter_binary: bool, calculate_tokens: bool) -> str:
        """运行工具并返回目录内容的字符串表示"""
        target_path, error = self.get_safe_path(relative_workspace_path)
        if error:
            return error

        if not target_path.exists():
            return f"错误：路径不存在: {target_path}"

        if not target_path.is_dir():
            return f"错误：路径不是目录: {target_path}"

        try:
            filter_mode = "只显示文本/代码文件" if filter_binary else "显示所有文件"
            token_mode = "计算token数量" if calculate_tokens else "不计算token数量"
            # 更新初始输出行，描述新的扁平格式
            output_lines = [f"Contents of directory '{relative_workspace_path}' (Level {level}, {filter_mode}, {token_mode}, Format: path: type attributes timestamp):\n"]

            # 重置统计数据
            total_items = 0
            filtered_items = 0

            # 从1开始计算层级，1表示第一层，即根目录
            # 不再需要传递 prefix 参数
            self._list_directory_recursive(
                target_path, 1, output_lines,
                stats=(total_items, filtered_items),
                max_level=level,
                filter_binary=filter_binary,
                calculate_tokens=calculate_tokens,
                base_dir=self.base_dir
            )

            if filter_binary and filtered_items > 0:
                output_lines.append(f"\n已过滤 {filtered_items} 个二进制文件（图片、视频等非文本文件）")

            return "".join(output_lines)

        except Exception as e:
            logger.error(f"列出目录内容时出错: {e}", exc_info=True)
            return f"列出目录内容时出错: {e!s}"

    def _is_text_file(self, file_path: Path) -> bool:
        """判断文件是否为文本/代码文件"""
        return is_text_file(file_path)

    def _list_directory_recursive(
        self, current_path: Path, current_level: int,
                                 output_lines: List[str], # 移除 prefix 参数
        stats: Tuple[int, int] = (0, 0),
        max_level: int = 1,
        filter_binary: bool = True,
        calculate_tokens: bool = True,
        base_dir: Path = None
    ) -> Tuple[int, int]:
        """递归地列出目录内容（扁平格式），并返回统计数据（总项目数，被过滤的项目数）

        Args:
            current_path: 当前处理的路径
            current_level: 当前层级，从1开始（1=根目录）
            output_lines: 输出行列表
            stats: 统计信息元组 (总项目数, 过滤项目数)
            max_level: 最大递归层级
            filter_binary: 是否过滤二进制文件
            calculate_tokens: 是否计算文本文件的token数量
            base_dir: 基础目录路径，用于计算相对路径

        Returns:
            更新后的统计信息元组
        """
        total_items, filtered_items = stats

        # 检查是否超出最大层级限制（不包括等于的情况）
        if current_level > max_level:
            return total_items, filtered_items

        try:
            items = sorted(
                list(current_path.iterdir()),
                key=lambda x: (not x.is_dir(), x.name.lower())
            )
        except PermissionError:
            # 使用新的扁平错误格式
            relative_path = str(current_path.relative_to(base_dir)) if base_dir and current_path.is_relative_to(base_dir) else str(current_path)
            output_lines.append(f"{relative_path}/: error Permission denied\n")
            return total_items, filtered_items
        except Exception as e:
            # 使用新的扁平错误格式
            relative_path = str(current_path.relative_to(base_dir)) if base_dir and current_path.is_relative_to(base_dir) else str(current_path)
            output_lines.append(f"{relative_path}/: error Cannot access directory: {e!s}\n")
            return total_items, filtered_items

        # 如果过滤二进制文件，则先筛选
        if filter_binary:
            filtered_file_items = [item for item in items if item.is_dir() or self._is_text_file(item)]
            filtered_items += len(items) - len(filtered_file_items)
            items = filtered_file_items

        # 检查目录是否为空
        if len(items) == 0:
            relative_path = str(current_path.relative_to(base_dir)) if base_dir and current_path.is_relative_to(base_dir) else str(current_path)
            output_lines.append(f"{relative_path}/: 目录为空，没有文件\n")
            return total_items, filtered_items

        for i, item in enumerate(items):
            total_items += 1
            # 移除 is_last, connector, new_prefix 的计算和使用

            relative_item_path = str(item.relative_to(base_dir))

            if item.is_dir():
                # 统计下一层目录的文件数量
                try:
                    sub_items = list(item.iterdir())
                    if filter_binary:
                        sub_items = [sub_item for sub_item in sub_items if sub_item.is_dir() or self._is_text_file(sub_item)]
                    item_count = f"{len(sub_items)} items"
                except (PermissionError, Exception):
                    item_count = "? items"  # 如果无法访问子目录，则显示为未知

                info = DirectoryInfo(
                    name=item.name,
                    path=relative_item_path, # 使用计算好的相对路径
                    is_dir=True,
                    item_count=item_count,
                    last_modified=item.stat().st_mtime,
                )
                # 修改输出格式为：path/: d item_count timestamp
                output_lines.append(f"{info.path}/: d {info.item_count:>10} {info.format_time()}\n") # 使用 >10 简单右对齐

                # 只有当当前层级小于最大层级时才继续递归
                if current_level < max_level:
                    # 递归处理子目录，层级+1，不再传递 prefix
                    total_items, filtered_items = self._list_directory_recursive(
                        item, current_level + 1, output_lines, # 移除 new_prefix
                        (total_items, filtered_items),
                        max_level, filter_binary, calculate_tokens, base_dir
                    )
            else: # 处理文件
                try:
                    stat_result = item.stat()
                    file_size = stat_result.st_size

                    # 对于文本文件计算行数和token数量
                    line_count = None
                    token_count = None

                    if self._is_text_file(item):
                        line_count = self._count_lines(item)
                        # 仅在需要计算token时计算
                        if calculate_tokens:
                            token_count = self._count_tokens(item)

                    info = FileInfo(
                        name=item.name,
                        path=relative_item_path, # 使用计算好的相对路径
                        is_dir=False,
                        size=file_size,
                        line_count=line_count,
                        last_modified=stat_result.st_mtime,
                    )

                    size_str = self._format_size(info.size)
                    # 组合属性字符串，注意处理 None 值和空格
                    attributes = [size_str]
                    if info.line_count is not None:
                        attributes.append(f"{info.line_count} lines")
                    if token_count is not None:
                        attributes.append(f"{token_count} tokens")
                    attributes_str = ", ".join(attributes)

                    # 修改输出格式为：path: - attributes timestamp
                    output_lines.append(f"{info.path}: - {attributes_str:<30} {info.format_time()}\n") # 使用 <30 简单左对齐

                except Exception as file_e:
                     # 使用新的扁平错误格式
                     output_lines.append(f"{relative_item_path}: error Cannot access file: {file_e!s}\n")

        return total_items, filtered_items

    def _count_lines(self, file_path: Path) -> Optional[int]:
        """计算文件行数"""
        return count_file_lines(file_path)

    def _count_tokens(self, file_path: Path) -> Optional[int]:
        """计算文件token数量"""
        return count_file_tokens(file_path)

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        return format_file_size(size)

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
        path = "."
        if arguments and "relative_workspace_path" in arguments:
            path = arguments["relative_workspace_path"]

        return {
            "action": "查看工作区内的文件",
            "remark": path
        }

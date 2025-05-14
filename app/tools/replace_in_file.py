import os
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
import difflib
import re

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

# 语言控制常量：True 为中文，False 为英文
USE_CHINESE = True


class ReplaceInFileParams(BaseToolParams):
    """文件内容替换参数"""
    file_path: str = Field(
        ...,
        description="要修改的文件路径，可以是相对于工作目录的路径或绝对路径" if USE_CHINESE else
                   "File path to modify, relative to the working directory or absolute path"
    )
    diff: str = Field(
        ...,
        description="包含 SEARCH/REPLACE 块的差异内容，用于定义要查找和替换的内容。SEARCH块中的内容必须与文件中的内容完全匹配（包括空格、换行和缩进）。建议先使用read_file查看文件内容再编写替换。请勿使用git diff格式。" if USE_CHINESE else
                   "Diff content with SEARCH/REPLACE blocks defining what to find and replace. SEARCH block content must EXACTLY match the file content (including spaces, line breaks, and indentation). It's recommended to use read_file first to view the content before writing replacements. Do NOT use git diff format."
    )


class ReplaceResult(NamedTuple):
    """替换结果详情"""
    new_content: str  # 替换后的内容
    added_lines: int  # 新增行数
    deleted_lines: int  # 删除行数
    modified_lines: int  # 修改行数
    total_changed_lines: int  # 变更总行数
    size_change: int  # 文件大小变化（字节）
    blocks_info: List[Dict[str, Any]]  # 每个替换块的信息
    diff_view: Optional[str] = None  # 新增字段，用于存储 diff 视图


@tool()
class ReplaceInFile(AbstractFileTool[ReplaceInFileParams], WorkspaceGuardTool[ReplaceInFileParams]):
    # Diff视图配置常量
    DEFAULT_DIFF_CONTEXT_LINES = 5  # Diff 上下文行数
    DEFAULT_DIFF_OMIT_THRESHOLD = 10  # Diff 中连续变更行数超过此阈值则省略中间部分
    DEFAULT_DIFF_OMIT_RETAIN_LINES = 3  # Diff 省略时，在大型变更块首尾保留的行数

    # 这里由于是动态生成，所以不能使用类注释
    description = """
    文件内容精确替换工具，用于对现有文件进行精确的局部修改。
    重要提示：仅使用 SEARCH/REPLACE 格式 - 请勿使用 git diff 格式。
    SEARCH块中的内容必须与文件中的内容完全匹配（逐字符匹配，包括所有空格、换行和缩进）。
    在使用此工具前，建议先使用 read_file 工具查看文件的准确内容。
    若替换频繁失败，请尝试使用 write_to_file 工具来重写整个文件，若文件已经较大，请使用 write_to_file 工具来重写文件开头，再使用本工具进行追加。
    请参考系统提示中的工具参考文档获取详细的使用说明和示例。
    """ \
        if USE_CHINESE else \
    """
    File Content Precise Replacement Tool for making targeted modifications to existing files.
    Important: Use SEARCH/REPLACE format only - NOT git diff format.
    SEARCH block content must EXACTLY match the file content (character-by-character, including all spaces, line breaks, and indentation).
    It's recommended to use the read_file tool first to view the exact file content before using this tool.
    If replacement fails frequently, try using the write_to_file tool to rewrite the entire file. If the file is large, use the write_to_file tool to rewrite the beginning of the file, then use this tool for appending.
    Please refer to the tool reference in the system prompt for detailed usage instructions and examples.
    """

    def get_prompt_hint(self) -> str:
        """生成包含工具详细使用说明的XML格式提示信息"""
        if USE_CHINESE:
            hint = """<tool name="replace_in_file">
  <description>
    使用 SEARCH/REPLACE 块精确修改文件的特定部分。
    当需要进行精确的局部更改而非替换整个文件时使用此工具。
    如果需要复制或移动文件，请使用 shell_exec 工具来执行 cp 或 mv 命令。
  </description>
  <parameters>
    <param name="file_path" type="string" required="true">要修改的文件路径</param>
    <param name="diff" type="string" required="true">定义要查找和替换内容的 SEARCH/REPLACE 块</param>
  </parameters>
  <format>
    <block>
      <![CDATA[
<<<<<<< SEARCH
[要查找的精确内容，必须与文件中的内容完全匹配]
=======
[要替换成的内容]
>>>>>>> REPLACE
      ]]>
    </block>
  </format>
  <critical_rules>
    <rule>SEARCH 内容必须精确匹配（包括空格、缩进、换行和行尾，逐字符匹配）</rule>
    <rule>SEARCH 块必须包含完整的行 - 无法匹配部分行或行内片段</rule>
    <rule>建议先使用 read_file 工具查看文件内容，确保 SEARCH 块内容准确</rule>
    <rule>SEARCH/REPLACE 块仅替换第一个匹配项</rule>
    <rule>按照文件中出现的顺序列出多个块</rule>
    <rule>Keep blocks concise - include just enough lines to uniquely identify sections</rule>
  </critical_rules>
  <common_errors>
    <error>Match failures typically occur because the SEARCH block doesn't exactly match file content, including invisible spaces or line breaks</error>
    <error>If file contains Markdown or other formatting, ensure you include all markers and formatting characters</error>
    <error>Using shorter SEARCH blocks can reduce the chance of matching errors</error>
  </common_errors>
  <special_operations>
    <operation>移动代码：使用两个块（一个删除，一个插入）</operation>
    <operation>删除代码：使用空的 REPLACE 部分</operation>
    <operation>完整替换文件：使用 write_to_file 工具</operation>
  </special_operations>
  <example>
    <![CDATA[
replace_in_file(
  file_path="app/models.py",
  diff="<<<<<<< SEARCH
class User:
    def __init__(self, name):
        self.name = name
=======
class User:
    def __init__(self, name, email=None):
        self.name = name
        self.email = email
>>>>>>> REPLACE"
)
    ]]>
  </example>
</tool>"""
        else:
            hint = """<tool name="replace_in_file">
  <description>
    Precisely modify specific parts of files using SEARCH/REPLACE blocks.
    Use when you need targeted changes rather than replacing entire files.
  </description>
  <parameters>
    <param name="file_path" type="string" required="true">File path to modify</param>
    <param name="diff" type="string" required="true">SEARCH/REPLACE blocks defining content to find and replace</param>
  </parameters>
  <format>
    <block>
      <![CDATA[
<<<<<<< SEARCH
[Exact content to find - must match the file content precisely]
=======
[Content to replace with]
>>>>>>> REPLACE
      ]]>
    </block>
  </format>
  <critical_rules>
    <rule>SEARCH content must match EXACTLY (including whitespace, indentation, newlines and line endings, character-by-character)</rule>
    <rule>SEARCH blocks must contain COMPLETE lines - partial lines or fragments within a line CANNOT be matched</rule>
    <rule>Always use read_file tool first to view the file content and ensure SEARCH block accuracy</rule>
    <rule>SEARCH/REPLACE blocks replace only the first match occurrence</rule>
    <rule>List multiple blocks in the order they appear in the file</rule>
    <rule>Keep blocks concise - include just enough lines to uniquely identify sections</rule>
  </critical_rules>
  <common_errors>
    <error>Match failures typically occur because the SEARCH block doesn't exactly match file content, including invisible spaces or line breaks</error>
    <error>If file contains Markdown or other formatting, ensure you include all markers and formatting characters</error>
    <error>Using shorter SEARCH blocks can reduce the chance of matching errors</error>
  </common_errors>
  <special_operations>
    <operation>To move code: Use two blocks (one to delete, one to insert)</operation>
    <operation>To delete code: Use empty REPLACE section</operation>
    <operation>For full file replacement: Use write_to_file tool instead</operation>
  </special_operations>
  <example>
    <![CDATA[
replace_in_file(
  file_path="app/models.py",
  diff="<<<<<<< SEARCH
class User:
    def __init__(self, name):
        self.name = name
=======
class User:
    def __init__(self, name, email=None):
        self.name = name
        self.email = email
>>>>>>> REPLACE"
)
    ]]>
  </example>
</tool>"""

        return hint

    async def execute(self, tool_context: ToolContext, params: ReplaceInFileParams) -> ToolResult:
        """
        执行文件内容替换操作

        Args:
            tool_context: 工具上下文
            params: 参数对象，包含文件路径和差异内容

        Returns:
            ToolResult: 包含操作结果
        """
        try:
            # 使用父类方法获取安全的文件路径
            file_path, error = self.get_safe_path(params.file_path)
            if error:
                return ToolResult(ok=False, content=error)

            # 检查文件是否存在
            if not file_path.exists():
                error_msg = f"文件不存在: {file_path}" if USE_CHINESE else f"File does not exist: {file_path}"
                return ToolResult(ok=False, content=error_msg)

            # 读取原始文件内容
            original_content = await self._read_file(file_path)

            # 构建新的文件内容并获取变更统计
            try:
                replace_result = await self._construct_new_file_content(params.diff, original_content, os.path.basename(file_path))
                new_content = replace_result.new_content
            except Exception as e:
                if USE_CHINESE:
                    return ToolResult(content=f"无法构建新的文件内容: {e!s}。\n"
                    "建议:\n"
                    "1. 检查您的 SEARCH 块是否与文件内容精确匹配\n"
                    "2. 将大型更改拆分为多个较小的 SEARCH/REPLACE 块\n"
                    "3. 确保块按照它们在文件中出现的顺序排列\n"
                    "4. 验证空格、缩进和行尾完全匹配\n"
                    "5. 重要提示: SEARCH 块必须包含文件中的完整行。无法匹配部分行或行内片段。\n"
                    "6. 使用正确的格式: <<<<<<< SEARCH / >>>>>>> REPLACE\n"
                    "7. 对于复杂的替换，请先使用 read_file 工具检查精确内容")
                else:
                    return ToolResult(ok=False, content=f"Failed to construct new file content: {e!s}.\n"
                    "Suggestions:\n"
                    "1. Check that your SEARCH blocks accurately match the file content\n"
                    "2. Break large changes into multiple smaller SEARCH/REPLACE blocks\n"
                    "3. Ensure blocks are in the order they appear in the file\n"
                    "4. Verify whitespace, indentation, and line endings match exactly\n"
                    "5. CRITICAL: SEARCH blocks must contain COMPLETE lines from the file. Partial lines or fragments within a line CANNOT be matched.\n"
                    "6. Use the correct format: <<<<<<< SEARCH / >>>>>>> REPLACE\n"
                    "7. For complex replacements, first use read_file to examine the exact content")

            # 如果内容没有变化，返回提示信息（改为报错）
            if original_content == new_content:
                if USE_CHINESE:
                    return ToolResult(ok=False, content=f"替换失败: 未找到匹配内容。请检查 SEARCH 块。文件内容未更改: {file_path}\n"
                    "可能的原因:\n"
                    "1. SEARCH 内容与文件的任何部分都不完全匹配\n"
                    "2. 空格或行尾与文件中的不同\n"
                    "3. 自上次读取后文件可能已被修改\n"
                    "4. 您可能使用了不正确的格式 - 请使用 <<<<<<< SEARCH / >>>>>>> REPLACE 格式\n"
                    "5. 重要提示: SEARCH 块必须包含文件中的完整行。无法匹配部分行或行内片段。\n\n"
                    "建议先使用 read_file 工具查看文件当前内容，然后使用正确的 SEARCH/REPLACE 格式")
                else:
                    return ToolResult(ok=False, content=f"Replacement failed: No matching content found. Please check SEARCH blocks. File content unchanged: {file_path}\n"
                    "Possible reasons:\n"
                    "1. The SEARCH content doesn't match any part of the file exactly\n"
                    "2. Whitespace or line endings differ from what's in the file\n"
                    "3. The file may have been modified since you last read it\n"
                    "4. You might be using incorrect format - use <<<<<<< SEARCH / >>>>>>> REPLACE format\n"
                    "5. CRITICAL: SEARCH blocks must contain COMPLETE lines from the file. Partial lines or fragments within a line CANNOT be matched.\n\n"
                    "Try reading the file first with read_file tool to see its current content, then use the correct SEARCH/REPLACE format")

            # 写入新的文件内容
            await self._write_file(file_path, new_content)

            # 执行语法检查
            valid, errors = SyntaxChecker.check_syntax(str(file_path), new_content)

            # 如果语法检查失败，回滚修改
            if not valid:
                # 回滚到原始内容
                await self._write_file(file_path, original_content)
                logger.warning(f"检测到语法错误，已回滚文件 {file_path} 的修改")

                # 构建错误消息
                errors_str = "\n".join(errors)
                if USE_CHINESE:
                    error_message = f"操作已回滚: 文件中检测到语法问题:\n{errors_str}"
                else:
                    error_message = f"Operation rolled back: Syntax issues detected in file:\n{errors_str}"

                return ToolResult(ok=False, content=error_message)

            # 触发文件更新事件（只有在语法检查通过后才触发）
            await self._dispatch_file_event(tool_context, str(file_path), EventType.FILE_UPDATED)

            # 生成详细的变更统计信息
            file_name = os.path.basename(file_path)
            original_size = len(original_content.encode('utf-8'))
            new_size = len(new_content.encode('utf-8'))
            original_lines = original_content.count('\n') + (0 if original_content.endswith('\n') else 1)
            new_lines = new_content.count('\n') + (0 if new_content.endswith('\n') else 1)

            # 格式化块信息
            blocks_summary = []
            for block in replace_result.blocks_info:
                blocks_summary.append(
                    f"- Line {block['start_line']}-{block['end_line']}: {block['description']}"
                    f"({block['stats']})"
                )

            blocks_info_str = "\n".join(blocks_summary)

            # 生成格式化的输出
            if USE_CHINESE:
                output = (
                    f"文件已更新: {file_path} | "
                    f"+{replace_result.added_lines} 新增 "
                    f"-{replace_result.deleted_lines} 删除 "
                    f"~{replace_result.modified_lines} 修改 | "
                    f"总变更: {replace_result.total_changed_lines} 行 | "
                    f"大小: {'+' if replace_result.size_change > 0 else ''}{replace_result.size_change} 字节"
                    f"({original_size}→{new_size}) | "
                    f"行数: {original_lines}→{new_lines}\n\n"
                    f"替换块: \n{blocks_info_str}"
                )
                if replace_result.diff_view:  # 如果有 diff 视图，则追加
                    output += f"\n\n文件实际变更详情 (Diff，请基于此评估变更是否符合预期):\n{replace_result.diff_view}"
            else:
                output = (
                    f"File updated: {file_path} | "
                    f"+{replace_result.added_lines} added "
                    f"-{replace_result.deleted_lines} deleted "
                    f"~{replace_result.modified_lines} modified | "
                    f"Total changes: {replace_result.total_changed_lines} lines | "
                    f"Size: {'+' if replace_result.size_change > 0 else ''}{replace_result.size_change} bytes"
                    f"({original_size}→{new_size}) | "
                    f"Lines: {original_lines}→{new_lines}\n\n"
                    f"Replacement blocks: \n{blocks_info_str}"
                )
                if replace_result.diff_view:  # 如果有 diff 视图，则追加
                    output += f"\n\nFile Actual Change Details (Diff, please evaluate if the changes are as expected based on this):\n{replace_result.diff_view}"

            # 返回操作结果
            return ToolResult(content=output)

        except Exception as e:
            logger.exception(f"替换文件内容失败: {e!s}")
            if USE_CHINESE:
                return ToolResult(ok=False, content=f"替换文件内容失败: {e!s}")
            else:
                return ToolResult(ok=False, content=f"Failed to replace file content: {e!s}")

    async def _read_file(self, file_path: Path) -> str:
        """读取文件内容"""
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            return await f.read()

    async def _write_file(self, file_path: Path, content: str) -> None:
        """写入文件内容"""
        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(content)

    async def _construct_new_file_content(self, diff_content: str, original_content: str, file_name: str) -> ReplaceResult:
        """
        构建新的文件内容并统计变更情况

        Args:
            diff_content: 包含SEARCH/REPLACE块的差异内容
            original_content: 原始文件内容
            file_name: 文件名，用于 diff 视图的头部信息

        Returns:
            ReplaceResult: 包含新内容、变更统计和 diff 视图的对象
        """
        result = ""
        last_processed_index = 0
        added_lines = 0
        deleted_lines = 0
        modified_lines = 0
        blocks_info = []

        # 获取行号的辅助函数
        def get_line_number(index: int) -> int:
            if index <= 0:
                return 1
            return original_content[:index].count('\n') + 1

        # 分析SEARCH/REPLACE块
        search_replace_blocks = self._parse_search_replace_blocks(diff_content)
        match_strategies = {
            'exact': 0,
            'line': 0,
            'block': 0
        }

        # 空内容处理
        if not search_replace_blocks:
            return ReplaceResult(
                new_content=original_content,
                added_lines=0,
                deleted_lines=0,
                modified_lines=0,
                total_changed_lines=0,
                size_change=0,
                blocks_info=[],
                diff_view=None  # 空内容时，diff_view 为 None
            )

        for search_content, replace_content in search_replace_blocks:
            # 处理特殊情况：空的搜索内容
            if not search_content.strip():
                # 空搜索块处理
                if original_content.strip() == "":
                    # 全新文件：开始插入
                    search_match_index = 0
                    search_end_index = 0
                    strategy = 'exact'
                else:
                    # 完全替换整个文件
                    search_match_index = 0
                    search_end_index = len(original_content)
                    strategy = 'exact'
            else:
                # 查找匹配位置（使用三种策略）
                search_match_index, search_end_index, strategy = await self._find_match_position_with_strategy(
                    search_content, original_content, last_processed_index
                )

            # 检查是否找到匹配
            if search_match_index == -1:
                # 没有找到匹配内容，提供更具体的错误信息
                preview = search_content[:100] + ("..." if len(search_content) > 100 else "")
                context_lines = min(5, len(original_content.split('\n')))
                original_preview = "\n".join(original_content.split('\n')[:context_lines])
                if len(original_content.split('\n')) > context_lines:
                    original_preview += "\n..."

                if USE_CHINESE:
                    error_msg = (f"在文件中找不到与SEARCH块匹配的内容:\n{preview}\n\n"
                                f"文件开头:\n{original_preview}\n\n"
                                f"建议:\n"
                                f"1. 使用read_file工具确认精确内容\n"
                                f"2. 检查不可见字符、不同的缩进或行尾\n"
                                f"3. 尝试在SEARCH块中使用更少的行，使匹配更容易\n"
                                f"4. 确保使用正确的SEARCH/REPLACE格式，而非git diff格式\n"
                                f"5. SEARCH块必须包含文件中的完整行，不能匹配行内片段")
                else:
                    error_msg = (f"Could not find matching content in file for SEARCH block:\n{preview}\n\n"
                                f"File begins with:\n{original_preview}\n\n"
                                f"Suggestions:\n"
                                f"1. Confirm exact content with read_file tool\n"
                                f"2. Check for invisible characters, different indentation, or line endings\n"
                                f"3. Try using fewer lines in your SEARCH block to make matching easier\n"
                                f"4. Make sure you're using the correct SEARCH/REPLACE format, not git diff format\n"
                                f"5. SEARCH blocks must contain complete lines from the file, not fragments within a line")
                logger.error(error_msg)
                raise ValueError(error_msg)

            # 更新匹配策略统计
            if strategy:
                match_strategies[strategy] += 1

            # 添加匹配位置前的内容
            result += original_content[last_processed_index:search_match_index]

            # 统计变更行数
            search_lines = search_content.split('\n')
            replace_lines = replace_content.split('\n')

            # 移除末尾空行（如果有）
            if search_lines and search_lines[-1] == '':
                search_lines.pop()
            if replace_lines and replace_lines[-1] == '':
                replace_lines.pop()

            search_line_count = len(search_lines)
            replace_line_count = len(replace_lines)

            # 计算变更行数
            if search_line_count > replace_line_count:
                deleted_count = search_line_count - replace_line_count
                deleted_lines += deleted_count
                if replace_line_count > 0:
                    modified_lines += replace_line_count
            elif replace_line_count > search_line_count:
                added_count = replace_line_count - search_line_count
                added_lines += added_count
                if search_line_count > 0:
                    modified_lines += search_line_count
            else:
                # 行数相同，但内容可能不同
                modified_lines += search_line_count

            start_line = get_line_number(search_match_index)
            end_line = get_line_number(search_end_index)

            # 确定变更描述
            if search_line_count == 0 and replace_line_count > 0:
                description = "添加内容" if USE_CHINESE else "Added content"
                stats = f"{replace_line_count} " + ("新增" if USE_CHINESE else "added")
            elif search_line_count > 0 and replace_line_count == 0:
                description = "删除内容" if USE_CHINESE else "Deleted content"
                stats = f"{search_line_count} " + ("删除" if USE_CHINESE else "deleted")
            else:
                # 尝试从内容推断变更类型
                search_content_trimmed = search_content.strip()
                if search_content_trimmed.startswith("def ") or search_content_trimmed.startswith("class "):
                    function_text = "函数" if USE_CHINESE else "Function"
                    class_text = "类" if USE_CHINESE else "Class"
                    description = f"{function_text if 'def ' in search_content_trimmed else class_text} " + ("定义" if USE_CHINESE else "definition")
                elif "return" in search_content_trimmed:
                    description = "返回值" if USE_CHINESE else "Return value"
                elif search_line_count >= 5:
                    description = "代码块" if USE_CHINESE else "Code block"
                else:
                    description = "内容" if USE_CHINESE else "Content"

                # 格式化变更统计
                stats_parts = []
                if added_count := replace_line_count - min(search_line_count, replace_line_count):
                    stats_parts.append(f"{added_count} " + ("新增" if USE_CHINESE else "added"))
                if deleted_count := search_line_count - min(search_line_count, replace_line_count):
                    stats_parts.append(f"{deleted_count} " + ("删除" if USE_CHINESE else "deleted"))
                if min(search_line_count, replace_line_count) > 0:
                    stats_parts.append(f"{min(search_line_count, replace_line_count)} " + ("修改" if USE_CHINESE else "modified"))

                stats = ", ".join(stats_parts)

            # 记录替换块信息
            blocks_info.append({
                'start_line': start_line,
                'end_line': end_line,
                'search_lines': search_line_count,
                'replace_lines': replace_line_count,
                'description': description,
                'stats': stats,
                'strategy': strategy  # 记录使用的匹配策略
            })

            # 添加替换内容
            result += replace_content

            # 更新处理位置
            last_processed_index = search_end_index

        # 添加最后一个匹配位置后的所有内容
        result += original_content[last_processed_index:]

        # 计算总变更行数
        total_changed_lines = added_lines + deleted_lines + modified_lines

        # 计算大小变化（字节）
        size_change = len(result.encode('utf-8')) - len(original_content.encode('utf-8'))

        # 添加匹配策略信息
        strategy_summary = []
        for strategy, count in match_strategies.items():
            if count > 0:
                strategy_name = {
                    'exact': '精确匹配' if USE_CHINESE else 'Exact',
                    'line': '行级匹配' if USE_CHINESE else 'Line-level',
                    'block': '块锚点匹配' if USE_CHINESE else 'Block anchor'
                }.get(strategy, strategy)
                strategy_summary.append(f"{strategy_name}({count})")

        if strategy_summary:
            for block in blocks_info:
                if 'strategy' in block:
                    del block['strategy']  # 移除临时策略记录，防止输出太乱
                # 将策略信息添加到描述中
                original_desc = block.get('description', '')
                strategy_str = ", ".join(strategy_summary)
                if USE_CHINESE:
                    block['description'] = f"{original_desc} | 匹配: {strategy_str}"
                else:
                    block['description'] = f"{original_desc} | Match: {strategy_str}"

        # Ensure the final result ends with a newline if not empty
        if result and not result.endswith('\n'):
            result += '\n'

        # 生成 diff 视图
        diff_view_str = await self._generate_diff_view(
            original_content,
            result,  # 使用替换后的内容
            file_name,
            context_lines=self.DEFAULT_DIFF_CONTEXT_LINES,
            omit_threshold=self.DEFAULT_DIFF_OMIT_THRESHOLD,
            omit_retain_lines=self.DEFAULT_DIFF_OMIT_RETAIN_LINES
        )

        return ReplaceResult(
            new_content=result,
            added_lines=added_lines,
            deleted_lines=deleted_lines,
            modified_lines=modified_lines,
            total_changed_lines=total_changed_lines,
            size_change=size_change,
            blocks_info=blocks_info,
            diff_view=diff_view_str  # 添加 diff 视图
        )

    def _parse_search_replace_blocks(self, diff_content: str) -> List[Tuple[str, str]]:
        """
        解析SEARCH/REPLACE块

        Args:
            diff_content: 包含SEARCH/REPLACE块的差异内容

        Returns:
            List[Tuple[str, str]]: 搜索内容和替换内容的元组列表
        """
        blocks = []
        lines = diff_content.split("\n")

        # 检查和清理可能不完整的标记行
        if lines and (lines[-1].startswith("<") or lines[-1].startswith("=") or lines[-1].startswith(">")):
            if lines[-1] not in ["<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"]:
                # 记录一个警告，帮助调试可能的格式问题
                if USE_CHINESE:
                    logger.warning(f"移除可能不完整的标记行: '{lines[-1]}'. "
                                 f"有效的标记是 '<<<<<<< SEARCH', '=======', 和 '>>>>>>> REPLACE'.")
                else:
                    logger.warning(f"Removed possible incomplete marker line: '{lines[-1]}'. "
                                 f"Valid markers are '<<<<<<< SEARCH', '=======', and '>>>>>>> REPLACE'.")
                lines.pop()  # 移除可能不完整的标记行

        i = 0
        while i < len(lines):
            line = lines[i]

            if line == "<<<<<<< SEARCH":
                search_content = ""
                i += 1

                # 收集SEARCH内容直到遇到分隔符
                while i < len(lines) and lines[i] != "=======":
                    search_content += lines[i] + "\n"
                    i += 1

                if i < len(lines) and lines[i] == "=======":
                    replace_content = ""
                    i += 1

                    # 收集REPLACE内容直到遇到结束标记
                    while i < len(lines) and lines[i] != ">>>>>>> REPLACE":
                        replace_content += lines[i] + "\n"
                        i += 1

                    if i < len(lines) and lines[i] == ">>>>>>> REPLACE":
                        # 添加完整的SEARCH/REPLACE块
                        blocks.append((search_content, replace_content))
                    else:
                        if USE_CHINESE:
                            raise ValueError("SEARCH/REPLACE块格式错误: 缺少'>>>>>>> REPLACE'标记。\n"
                                           "每个块必须以'>>>>>>> REPLACE'精确结束。\n"
                                           "检查diff内容中是否有拼写错误或缺失行。")
                        else:
                            raise ValueError("SEARCH/REPLACE block format error: Missing '>>>>>>> REPLACE' marker.\n"
                                           "Each block must end with '>>>>>>> REPLACE' exactly as shown.\n"
                                           "Check for typos or missing lines in your diff content.")
                else:
                    if USE_CHINESE:
                        raise ValueError("SEARCH/REPLACE块格式错误: 缺少'======='分隔符。\n"
                                       "每个块必须在SEARCH和REPLACE部分之间有一个'======='行。\n"
                                       "格式应为:\n"
                                       "<<<<<<< SEARCH\n"
                                       "[要查找的内容]\n"
                                       "=======\n"
                                       "[要替换成的内容]\n"
                                       ">>>>>>> REPLACE")
                    else:
                        raise ValueError("SEARCH/REPLACE block format error: Missing '=======' separator.\n"
                                       "Each block must have a '=======' line between SEARCH and REPLACE sections.\n"
                                       "Format should be:\n"
                                       "<<<<<<< SEARCH\n"
                                       "[content to find]\n"
                                       "=======\n"
                                       "[content to replace with]\n"
                                       ">>>>>>> REPLACE")

            # 为了向后兼容，同时支持旧的格式 (>>>>>>> SEARCH 开始，<<<<<<< REPLACE 结束)
            elif line == ">>>>>>> SEARCH":
                search_content = ""
                i += 1

                # 收集SEARCH内容直到遇到分隔符
                while i < len(lines) and lines[i] != "=======":
                    search_content += lines[i] + "\n"
                    i += 1

                if i < len(lines) and lines[i] == "=======":
                    replace_content = ""
                    i += 1

                    # 收集REPLACE内容直到遇到结束标记
                    while i < len(lines) and lines[i] != "<<<<<<< REPLACE":
                        replace_content += lines[i] + "\n"
                        i += 1

                    if i < len(lines) and lines[i] == "<<<<<<< REPLACE":
                        # 添加完整的SEARCH/REPLACE块
                        blocks.append((search_content, replace_content))
                    else:
                        if USE_CHINESE:
                            raise ValueError("SEARCH/REPLACE块格式错误: 在旧格式中缺少'<<<<<<< REPLACE'标记。\n"
                                           "在旧格式中，每个块必须以'<<<<<<< REPLACE'精确结束，或使用新格式。\n"
                                           "检查diff内容中是否有拼写错误或缺失行。")
                        else:
                            raise ValueError("SEARCH/REPLACE block format error: Missing '<<<<<<< REPLACE' marker in old format.\n"
                                           "Each block must end with '<<<<<<< REPLACE' exactly as shown in old format, or use the new format.\n"
                                           "Check for typos or missing lines in your diff content.")
                else:
                    if USE_CHINESE:
                        raise ValueError("SEARCH/REPLACE块格式错误: 缺少'======='分隔符。\n"
                                       "每个块必须在SEARCH和REPLACE部分之间有一个'======='行。")
                    else:
                        raise ValueError("SEARCH/REPLACE block format error: Missing '=======' separator.\n"
                                       "Each block must have a '=======' line between SEARCH and REPLACE sections.")

            i += 1

        return blocks

    async def _find_match_position_with_strategy(
        self, search_content: str, original_content: str, start_index: int = 0
    ) -> Tuple[int, int, str]:
        """
        查找匹配位置，使用三种匹配策略，并返回使用的策略

        Args:
            search_content: 要查找的内容
            original_content: 原始文件内容
            start_index: 开始查找的位置索引

        Returns:
            Tuple[int, int, str]: 匹配的开始位置、结束位置和使用的策略名称
        """
        # 策略1: 精确匹配
        exact_index = original_content.find(search_content, start_index)
        if exact_index != -1:
            return exact_index, exact_index + len(search_content), 'exact'

        # 策略2: 行级修剪匹配（忽略行首尾空白）
        line_match = await self._line_trimmed_match(search_content, original_content, start_index)
        if line_match:
            return line_match[0], line_match[1], 'line'

        # 策略3: 块锚点匹配（对于较长内容块）
        search_lines = search_content.split("\n")
        if len(search_lines) >= 3:
            block_match = await self._block_anchor_match(search_content, original_content, start_index)
            if block_match:
                return block_match[0], block_match[1], 'block'

        # 没有找到匹配
        return -1, -1, ''

    async def _line_trimmed_match(
        self, search_content: str, original_content: str, start_index: int
    ) -> Optional[Tuple[int, int]]:
        """
        行级修剪匹配，忽略行首尾空白进行匹配

        使用类似TypeScript版本的实现，更加高效可靠地进行行级匹配

        Args:
            search_content: 要查找的内容
            original_content: 原始文件内容
            start_index: 开始查找的位置索引

        Returns:
            Optional[Tuple[int, int]]: 匹配的开始和结束位置，如果没有匹配则返回None
        """
        # 将两个内容拆分为行
        original_lines = original_content.split('\n')
        search_lines = search_content.split('\n')

        # 移除搜索内容末尾的空行（如果存在）
        if search_lines and search_lines[-1] == '':
            search_lines.pop()

        if not search_lines:  # 防止空搜索内容
            return None

        # 找到start_index所在的行号
        start_line_num = 0
        current_index = 0
        while current_index < start_index and start_line_num < len(original_lines):
            current_index += len(original_lines[start_line_num]) + 1  # +1 是为了换行符
            start_line_num += 1

        # 遍历原始内容中所有可能的起始位置
        for i in range(start_line_num, len(original_lines) - len(search_lines) + 1):
            matches = True

            # 尝试从此位置匹配所有搜索行
            for j in range(len(search_lines)):
                original_trimmed = original_lines[i + j].strip()
                search_trimmed = search_lines[j].strip()

                if original_trimmed != search_trimmed:
                    matches = False
                    break

            # 如果找到匹配，计算精确的字符位置
            if matches:
                # 计算开始字符索引
                match_start_index = 0
                for k in range(i):
                    match_start_index += len(original_lines[k]) + 1  # +1 为换行符

                # 计算结束字符索引
                match_end_index = match_start_index
                for k in range(len(search_lines)):
                    match_end_index += len(original_lines[i + k]) + 1  # +1 为换行符

                return match_start_index, match_end_index

        return None

    async def _block_anchor_match(
        self, search_content: str, original_content: str, start_index: int
    ) -> Optional[Tuple[int, int]]:
        """
        块锚点匹配，使用首尾行作为锚点定位匹配区域

        专为较长代码块（3行以上）设计的匹配策略，利用首尾行作为锚点，
        即使中间内容有细微差异也能成功匹配

        Args:
            search_content: 要查找的内容
            original_content: 原始文件内容
            start_index: 开始查找的位置索引

        Returns:
            Optional[Tuple[int, int]]: 匹配的开始和结束位置，如果没有匹配则返回None
        """
        # 将内容拆分为行
        original_lines = original_content.split('\n')
        search_lines = search_content.split('\n')

        # 只对3行以上的块使用此方法，避免误匹配
        if len(search_lines) < 3:
            return None

        # 移除尾部空行（如果存在）
        if search_lines and search_lines[-1] == '':
            search_lines.pop()

        # 提取首行和尾行作为锚点（去除空白）
        first_line_search = search_lines[0].strip()
        last_line_search = search_lines[-1].strip()
        search_block_size = len(search_lines)

        # 找到start_index所在的行号
        start_line_num = 0
        current_index = 0
        while current_index < start_index and start_line_num < len(original_lines):
            current_index += len(original_lines[start_line_num]) + 1
            start_line_num += 1

        # 寻找匹配的首尾锚点
        for i in range(start_line_num, len(original_lines) - search_block_size + 1):
            # 检查首行是否匹配
            if original_lines[i].strip() != first_line_search:
                continue

            # 检查尾行是否在预期位置匹配
            if original_lines[i + search_block_size - 1].strip() != last_line_search:
                continue

            # 计算精确的字符位置
            match_start_index = 0
            for k in range(i):
                match_start_index += len(original_lines[k]) + 1

            match_end_index = match_start_index
            for k in range(search_block_size):
                match_end_index += len(original_lines[i + k]) + 1

            return match_start_index, match_end_index

        return None

    async def _process_hunk_for_omission(
        self,
        lines: List[str],
        omit_threshold: int,
        omit_retain_lines: int
    ) -> List[str]:
        """
        处理单个连续的变更块（纯增加或纯删除），如果超过阈值则省略中间部分。

        Args:
            lines: 连续的变更行列表（例如，所有以 '+' 开头或所有以 '-' 开头的行）。
            omit_threshold: 触发省略的行数阈值。
            omit_retain_lines: 省略时，在块首尾保留的行数。

        Returns:
            List[str]: 处理后的行列表，可能包含省略标记。
        """
        if not lines:
            return []

        if len(lines) > omit_threshold and len(lines) > 2 * omit_retain_lines:
            hidden_count = len(lines) - 2 * omit_retain_lines
            processed_lines = lines[:omit_retain_lines]
            omission_marker = f"... ({hidden_count} line{'s' if hidden_count > 1 else ''} hidden) ..."
            # 保持与 diff 输出一致的标记风格，通常 diff 工具不会为省略标记添加 +/-
            # 但为了视觉上清晰，我们可以考虑添加，或者保持原样由 _generate_diff_view 处理
            # 这里暂时不添加 +/- ，由 difflib 生成的原始标记决定
            processed_lines.append(omission_marker)
            processed_lines.extend(lines[-omit_retain_lines:])
            return processed_lines
        return lines

    async def _generate_diff_view(
        self,
        original_content: str,
        new_content: str,
        file_name: str,
        context_lines: int,
        omit_threshold: int,
        omit_retain_lines: int
    ) -> Optional[str]:
        """
        生成类似 GitHub 的 Diff 视图。

        Args:
            original_content: 原始文件内容。
            new_content: 修改后的文件内容。
            file_name: 文件名，用于 Diff 头部。
            context_lines: Diff 上下文行数。
            omit_threshold: 触发省略的连续变更行数阈值。
            omit_retain_lines: 省略时，在大型变更块首尾保留的行数。

        Returns:
            Optional[str]: 生成的 Diff 文本，如果无变化则返回 None。
        """
        if original_content == new_content:
            return None

        original_lines = original_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        # 使用 difflib 生成 unified diff
        diff = list(difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{file_name}",
            tofile=f"b/{file_name}",
            n=context_lines, # 控制上下文行数
            lineterm="" # 保持行尾与输入一致
        ))

        if not diff: # 如果 difflib 没有产生差异（理论上不应该，因为我们已经检查过内容不同）
            return None

        processed_diff = []
        # 跳过 diff 头部 '--- a/...' 和 '+++ b/...'
        if len(diff) > 0 and diff[0].startswith("---"):
            processed_diff.append(diff.pop(0).rstrip("\n"))
        if len(diff) > 0 and diff[0].startswith("+++"):
            processed_diff.append(diff.pop(0).rstrip("\n"))

        current_hunk_lines = []
        current_hunk_type = None # '+' or '-'

        for line_with_newline in diff:
            line = line_with_newline.rstrip("\n") # 移除可能的换行符，方便处理
            if line.startswith("@@"):
                # 处理上一个累积的 hunk
                if current_hunk_lines:
                    processed_diff.extend(
                        await self._process_hunk_for_omission(
                            current_hunk_lines, omit_threshold, omit_retain_lines
                        )
                    )
                    current_hunk_lines = []
                processed_diff.append(line)
                current_hunk_type = None
            elif line.startswith("+") and not line.startswith("+++"):
                if current_hunk_type == '-': # 从删除切换到增加
                    processed_diff.extend(
                        await self._process_hunk_for_omission(
                            current_hunk_lines, omit_threshold, omit_retain_lines
                        )
                    )
                    current_hunk_lines = []
                current_hunk_lines.append(line)
                current_hunk_type = '+'
            elif line.startswith("-") and not line.startswith("---"):
                if current_hunk_type == '+': # 从增加切换到删除
                    processed_diff.extend(
                        await self._process_hunk_for_omission(
                            current_hunk_lines, omit_threshold, omit_retain_lines
                        )
                    )
                    current_hunk_lines = []
                current_hunk_lines.append(line)
                current_hunk_type = '-'
            else: # 上下文行或 hunk 结束
                if current_hunk_lines:
                    processed_diff.extend(
                        await self._process_hunk_for_omission(
                            current_hunk_lines, omit_threshold, omit_retain_lines
                        )
                    )
                    current_hunk_lines = []
                processed_diff.append(line)
                current_hunk_type = None

        # 处理最后一个累积的 hunk (如果有)
        if current_hunk_lines:
            processed_diff.extend(
                await self._process_hunk_for_omission(
                    current_hunk_lines, omit_threshold, omit_retain_lines
                )
            )

        # 确保每行都以换行符结尾，除了最后一行（如果diff本身就没有）
        # difflib.unified_diff 输出的行通常已经包含了换行符
        # 我们在处理时 rstrip 了，所以这里要加回去，除非是最后一行且原始diff就没有
        final_diff_output = []
        for i, l_str in enumerate(processed_diff):
            if i < len(processed_diff) -1 :
                 final_diff_output.append(l_str + "\n")
            else:
                # 检查原始的 diff 输出的最后一行是否带换行
                # difflib.unified_diff 的特性是如果文件的最后一行没有换行符，它生成的diff行的最后也不会有
                # 但通常文本文件最后一行有换行符。
                # 为了简化，我们这里统一为最后一行也添加换行符，除非它是空的
                if l_str:
                    final_diff_output.append(l_str + "\n")
                elif final_diff_output and final_diff_output[-1] == "\n": #避免双换行
                    pass #前一行已经是纯换行了
                elif final_diff_output: # 前面有内容，但此行为空，可以加个换行
                     final_diff_output.append("\n")


        return "".join(final_diff_output).rstrip("\n") # 最后移除末尾可能的多余换行

    async def get_tool_detail(self, tool_context: ToolContext, result: ToolResult, arguments: Dict[str, Any] = None) -> Optional[ToolDetail]:
        """
        获取工具详情

        Args:
            tool_context: 工具上下文
            result: 工具执行结果
            arguments: 工具参数

        Returns:
            Optional[ToolDetail]: 工具详情，如果没有则返回None
        """

        if not result.ok:
            return None

        if not arguments or "file_path" not in arguments:
            logger.warning("没有提供file_path参数")
            return None

        file_path, error = self.get_safe_path(arguments["file_path"])
        if error:
            logger.error(f"获取文件路径失败: {error}, file_path: {arguments['file_path']}")
            return None

        file_name = os.path.basename(file_path)

        # 使用 AbstractFileTool 的方法获取显示类型
        display_type = self.get_display_type_by_extension(file_path)

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

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
        if not result.ok:
            return {
                "action": "",
                "remark": ""
            }

        file_path = arguments["file_path"]
        file_name = os.path.basename(file_path)
        return {
            "action": "更新文件" if USE_CHINESE else "Update file",
            "remark": file_name
        }

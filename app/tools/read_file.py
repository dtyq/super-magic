import os
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles
import aiofiles.os # Keep this for os.path.exists etc.
from pydantic import Field

from app.tools.abstract_file_tool import AbstractFileTool

from markitdown import MarkItDown, StreamInfo
# Keep Excel and CSV converters if needed for other types
from app.tools.markitdown_plugins.excel_plugin import ExcelConverter
from app.tools.markitdown_plugins.csv_plugin import CSVConverter
# Import the new local PDF converter utility
from app.utils.pdf_converter_utils import convert_pdf_locally

from agentlang.context.tool_context import ToolContext
from app.core.entity.message.server_message import DisplayType, FileContent, ToolDetail
from agentlang.tools.tool_result import ToolResult
from agentlang.logger import get_logger
from app.tools.core import BaseToolParams, tool
from app.tools.workspace_guard_tool import WorkspaceGuardTool
from agentlang.utils.token_estimator import num_tokens_from_string

logger = get_logger(__name__) # noqa: F811

# 设置最大Token限制
MAX_TOTAL_TOKENS = 30000


class ReadFileParams(BaseToolParams):
    """读取文件参数"""
    file_path: str = Field(..., description="要读取的文件路径，相对于工作目录或绝对路径")
    offset: int = Field(0, description="开始读取的行号（从0开始）")
    limit: int = Field(200, description="要读取的行数或页数，默认200行，如果要读取整个文件，请设置为-1")


@tool()
class ReadFile(AbstractFileTool[ReadFileParams], WorkspaceGuardTool[ReadFileParams]):
    """读取文件内容工具

    这个工具可以读取指定路径的文件内容，支持文本文件、PDF和DOCX等格式。

    支持的文件类型：
    - 文本文件（.txt、.md、.py、.js等）
    - PDF文件（.pdf）
        - 若需要读取扫描件，请使用更为昂贵的 convert_pdf 工具转为 Markdown 格式后再使用本工具读取
        - 读取 PDF 文件时，会自动创建 Markdown 映射文件，后续读取 PDF 文件时会读取 Markdown 映射文件，而不是真地读取原始文件
        - 你可以将读取操作当成 PDF 转换工具使用，对于非扫描件的 PDF 文件，自动转换后的 Markdown 文件可以被任意使用
    - Word文档（.docx）
    - Jupyter Notebook（.ipynb）
    - Excel文件（.xls、.xlsx）
    - CSV文件（.csv）

    注意：
    - 读取工作目录外的文件被禁止
    - 二进制文件可能无法正确读取
    - 过大的文件将被拒绝读取，你必须分段读取部分内容来理解文件概要
    - 对于Excel和CSV文件，建议使用代码处理数据而不是直接使用文本内容
    - 为避免内容过长，一次性读取超过30000 token 时会自动截断内容，必须阅读完整的情况下，你可以分多次读取
    """

    # Excel处理的最大行数限制
    EXCEL_MAX_ROWS = 1000
    EXCEL_MAX_PREVIEW_ROWS = 50

    md = MarkItDown()
    # Remove PDFConverter registration here, it's handled in the util
    md.register_converter(ExcelConverter())
    md.register_converter(CSVConverter())

    async def execute(self, tool_context: ToolContext, params: ReadFileParams) -> ToolResult:
        """
        执行文件读取操作

        Args:
            tool_context: 工具上下文
            params: 文件读取参数

        Returns:
            ToolResult: 包含文件内容或错误信息
        """
        return await self.execute_purely(params)

    async def execute_purely(self, params: ReadFileParams) -> ToolResult:
        """
        执行文件读取操作，无需工具上下文参数

        Args:
            params: 文件读取参数

        Returns:
            ToolResult: 包含文件内容或错误信息
        """
        try:
            # 使用父类方法获取安全的文件路径
            file_path, error = self.get_safe_path(params.file_path)
            if error:
                return ToolResult(error=error)

            original_file_name = file_path.name # Store original name before path changes
            read_path = file_path  # 默认读取原始文件路径
            cache_just_created = False # Flag to indicate if cache was created in this call
            # 标记本次调用是否创建了缓存

            # --- PDF 缓存处理逻辑 ---
            if file_path.suffix.lower() == '.pdf':
                cache_md_path = file_path.with_suffix('.md')
                try:
                    cache_exists = await aiofiles.os.path.exists(cache_md_path)

                    if cache_exists:
                        logger.info(f"使用缓存文件: {cache_md_path} 读取 PDF 内容: {file_path}")
                        read_path = cache_md_path # 设置读取路径为缓存文件
                        cache_just_created = False
                    else:
                        logger.info(f"缓存文件 {cache_md_path} 不存在，尝试本地转换: {file_path}")
                        # 调用工具函数获取 Markdown 文本
                        markdown_content = await convert_pdf_locally(file_path)

                        if markdown_content is None:
                            # 转换失败
                            logger.error(f"本地 PDF 转换失败，无法读取: {file_path}")
                            return ToolResult(error=f"无法转换 PDF 文件 '{file_path.name}' 为 Markdown。")

                        # 转换成功，写入缓存文件
                        try:
                            async with aiofiles.open(cache_md_path, "w", encoding="utf-8") as cache_f:
                                await cache_f.write(markdown_content)
                            logger.info(f"已成功创建 PDF 缓存文件: {cache_md_path}")
                            cache_just_created = True # 标记缓存刚刚创建
                            read_path = cache_md_path # 设置读取路径为新创建的缓存
                        except Exception as write_e:
                            logger.exception(f"写入 PDF 缓存文件失败 ({cache_md_path}): {write_e!s}")
                            # 即使写入缓存失败，也尝试返回转换后的内容，但不设置 read_path
                            # 或者返回错误？这里选择返回错误，因为无法保证后续一致性
                            return ToolResult(error=f"PDF 转换成功但写入缓存文件 '{cache_md_path.name}' 失败: {write_e!s}")

                except Exception as e:
                    # 捕获检查缓存或转换/写入过程中的错误
                    logger.exception(f"处理 PDF 时出错 ({file_path}): {e!s}")
                    return ToolResult(error=f"处理 PDF 时出错: {e!s}")
            # --- PDF 缓存处理逻辑结束 ---


            # 检查最终的 read_path 是否有效
            if not await aiofiles.os.path.exists(read_path):
                 # This might happen if PDF conversion failed silently, cache was deleted, or it's another non-existent file
                 # 如果PDF转换静默失败、缓存被删除，或者这是另一个不存在的文件，可能会发生这种情况
                 return ToolResult(error=f"无法找到要读取的文件: {read_path} (原始请求: {original_file_name})")
            if await aiofiles.os.path.isdir(read_path):
                # 如果是 PDF 缓存路径变成目录，也报错
                return ToolResult(error=f"读取路径是个文件夹: {read_path} (原始请求: {original_file_name})，请使用 list_dir 工具获取文件夹内容")

            # --- 内容读取逻辑 ---
            read_extension = read_path.suffix.lower()
            # 定义需要 MarkItDown 处理的非文本扩展名（不包括 .pdf 和 .md）
            markitdown_extensions = {".ipynb", ".csv", ".xlsx", ".xls", ".docx"} # 添加或移除需要的格式

            content: str = ""
            is_binary = await self._is_binary_file(read_path)

            # 判断是否使用 MarkItDown
            use_markitdown = (
                read_extension in markitdown_extensions or
                (is_binary and read_extension not in {".md", ".txt", ".py", ".js", ".json", ".yaml", ".html", ".css"}) # 示例常见文本类型
            )

            if use_markitdown:
                 logger.info(f"文件 {read_path} (原始: {original_file_name}) 使用 markitdown 进行读取")
                 try:
                     # MarkItDown 需要二进制读取
                     async with aiofiles.open(read_path, "rb") as f:
                         # 传递原始的 offset 和 limit 给 MarkItDown (除了 PDF 缓存创建阶段)
                         # 注意：这里传递的是用户原始请求的 offset 和 limit
                         result = self.md.convert(f, stream_info=StreamInfo(extension=read_extension), offset=params.offset, limit=params.limit)
                         if not result or not result.markdown:
                             logger.warning(f"MarkItDown 转换返回空内容: {read_path}")
                             content = "[文件转换结果为空]"
                         else:
                             content = result.markdown
                 except Exception as e:
                     logger.exception(f"使用 MarkItDown 读取文件失败 ({read_path}): {e!s}")
                     return ToolResult(error=f"文件转换失败: {e!s}")
            else:
                 # 使用文本读取逻辑 (包括读取 .md 缓存)
                 logger.info(f"文件 {read_path} (原始: {original_file_name}) 使用文本读取逻辑")
                 if params.limit is None or params.limit <= 0:
                     content = await self._read_text_file(read_path)
                 else:
                     content = await self._read_text_file_with_range(
                         read_path, params.offset, params.limit
                     )
            # --- 内容读取逻辑结束 ---


            # 计算token数量并处理截断
            content_tokens = num_tokens_from_string(content)
            total_chars = len(content)
            content_truncated = False

            if content_tokens > MAX_TOTAL_TOKENS:
                logger.info(f"文件 {read_path.name} (原始: {original_file_name}) 内容token数 ({content_tokens}) 超出限制 ({MAX_TOTAL_TOKENS})，进行截断")
                content_truncated = True

                # 使用二分查找确定最佳截断点
                left, right = 0, len(content)
                best_content = ""
                best_tokens = 0

                while left <= right:
                    mid = (left + right) // 2
                    truncated = content[:mid]
                    tokens = num_tokens_from_string(truncated)

                    if tokens <= MAX_TOTAL_TOKENS:
                        best_content = truncated
                        best_tokens = tokens
                        left = mid + 1
                    else:
                        right = mid - 1

                content = best_content
                content_tokens = best_tokens
                truncation_note = f"\n\n[内容已截断：原始token数超过{MAX_TOTAL_TOKENS}的限制]"
                content += truncation_note

            # 添加文件元信息 - 使用 original_file_name 作为用户看到的文件名，read_path 用于内部信息
            shown_chars = len(content)
            truncation_status = "（已截断）" if content_truncated else ""
            meta_info = f"# 文件: {original_file_name}\n\n**文件信息**: 总字符数: {total_chars}，显示字符数: {shown_chars}{truncation_status}，Token数: {content_tokens}"
            if str(read_path) != str(file_path): # Only add if reading from a different path (e.g., cache)
                meta_info += f" (读取自: `{read_path.name}`)" # Use backticks for filename
            meta_info += "\n\n---\n\n" # Correct newline escaping
            raw_content = content # 存储未加 meta_info 的原始内容
            extra_info = {
                "raw_content": raw_content,
                "original_file_path": str(file_path),
                "read_path": str(read_path),
                "cache_just_created": cache_just_created # 也将缓存创建状态放入
            }

            # --- 如果适用，在此处附加缓存创建通知 ---
            if cache_just_created:
                cache_note = f"\n\n*注意：首次读取，已将源 PDF 文件 '{original_file_name}' 的内容转换为 Markdown 文件 '{read_path.name}' 并缓存。后续读取此 PDF 将直接使用此缓存文件。*"
                # 确保 cache_note 被添加到最终内容中
                # 如果内容被截断，追加到截断后的内容
                # Append cache note to the raw_content BEFORE meta_info is prepended
                raw_content += cache_note
            # --- 缓存通知结束 ---

            # Construct final content with meta info prepended to the potentially modified raw_content
            content_with_meta = meta_info + content # 使用可能被截断的 content

            return ToolResult(
                content=content_with_meta,
                extra_info=extra_info
            )

        except Exception as e:
            logger.exception(f"读取文件失败 (原始请求: {params.file_path}): {e!s}")
            return ToolResult(error=f"读取文件失败: {e!s}")

    async def _is_binary_file(self, file_path: Path) -> bool:
        """检查文件是否为二进制文件"""
        try:
            # 读取文件前4KB来判断是否为二进制文件
            chunk_size = 4 * 1024
            async with aiofiles.open(file_path, "rb") as f:
                chunk = await f.read(chunk_size)

                # 如果刚好是4KB边界，可能会截断UTF-8多字节字符，多读几个字节
                if len(chunk) == chunk_size:
                    # 定位到刚才读取的位置
                    await f.seek(0)
                    # 多读几个字节，确保完整的UTF-8字符
                    chunk = await f.read(chunk_size + 4)

            # 检查是否包含NULL字节（二进制文件的特征）
            if b"\x00" in chunk:
                return True

            # 尝试以UTF-8解码，如果失败则可能是二进制文件
            try:
                chunk.decode("utf-8")
                return False
            except UnicodeDecodeError:
                # 尝试使用ignore错误处理，如果内容大部分可以解析为文本，就不认为是二进制
                decoded = chunk.decode("utf-8", errors="ignore")
                # 如果解码后的文本长度至少是原始数据的25%，认为是文本文件
                if len(decoded) > len(chunk) * 0.25:
                    return False
                return True
        except Exception:
            # On error (e.g. permission denied), assume not binary or handle appropriately
            # 发生错误时（例如权限拒绝），适当地处理或假设不是二进制文件
            logger.warning(f"无法确定文件是否为二进制: {file_path}", exc_info=True)
            return False # Default to not binary if unsure
            # 如果不确定，默认为非二进制

    async def _read_text_file(self, file_path: Path) -> str:
        """读取整个文本文件内容"""
        async with aiofiles.open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return await f.read()

    async def _read_text_file_with_range(self, file_path: Path, offset: int, limit: int) -> str:
        """读取指定范围的文本文件内容

        Args:
            file_path: 文件路径
            offset: 起始行号（从0开始）
            limit: 要读取的行数，如果为负数则读取到文件末尾

        Returns:
            包含行号信息和指定范围内容的字符串，如果范围无效则返回提示信息
        """
        # 统计文件总行数并读取指定范围内容
        all_lines = []
        target_lines = []

        async with aiofiles.open(file_path, "r", encoding="utf-8", errors="replace") as f:
            line_idx = 0
            async for line in f:
                all_lines.append(line)
                # 根据行索引应用 offset 和 limit
                if limit > 0: # 如果 limit 是正数，从 offset 开始读取 limit 行
                    if offset <= line_idx < offset + limit:
                        target_lines.append(line)
                elif offset <= line_idx: # 如果 limit 不是正数（<=0 或 None），从 offset 读取到文件末尾
                    target_lines.append(line)
                line_idx += 1

        total_lines = len(all_lines)
        start_line = offset + 1  # 转为1-indexed便于用户理解

        # 构建结果头部信息
        if not target_lines:
            if offset >= total_lines:
                header = f"# 读取内容为空：起始行 {start_line} 超过文件总行数 {total_lines}\n\n"
            else:
                # Calculate the intended end line based on limit
                # 根据 limit 计算预期的结束行号
                end_line_intended = (offset + limit) if limit > 0 else total_lines
                header = f"# 读取内容为空：指定范围第 {start_line} 行到第 {end_line_intended} 行没有内容（文件共 {total_lines} 行）\n\n"
            return header
        else:
            # Actual end line is offset + number of lines read
            # 实际的结束行号是 offset + 读取的行数
            end_line_actual = offset + len(target_lines)
            header = f"# 显示第 {start_line} 行到第 {end_line_actual} 行（文件共 {total_lines} 行）\n\n"

        content = "".join(target_lines)

        # 添加省略标注
        has_prefix = offset > 0
        has_suffix = end_line_actual < total_lines

        if has_prefix:
            prefix_lines = offset
            prefix = f"# ... 前面有{prefix_lines}行  ...\n\n"
            content = prefix + content

        if has_suffix:
            suffix_lines = total_lines - end_line_actual
            suffix = f"\n\n# ... 后面还有{suffix_lines}行  ..."
            content = content + suffix

        return header + content

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
        if not result.ok or not result.extra_info or "raw_content" not in result.extra_info:
            return None

        # 从 extra_info 获取路径
        original_file_path_str = result.extra_info.get("original_file_path")
        read_path_str = result.extra_info.get("read_path")

        if not original_file_path_str or not read_path_str:
             logger.warning("无法从 extra_info 获取 original_file_path 或 read_path，尝试从 arguments 回退")
             # 可以尝试从 arguments 回退，或者直接返回 None
             if arguments and "file_path" in arguments:
                 original_file_path_str = arguments["file_path"]
                 # 如果没有 read_path, 只能猜测它和 original 一样
                 read_path_str = read_path_str or original_file_path_str
             else:
                  logger.error("无法确定文件路径信息，无法生成 ToolDetail")
                  return None


        original_file_name = os.path.basename(original_file_path_str)

        # Determine display type based on the ACTUAL file read (could be .md cache)
        # Use AbstractFileTool's method based on the path that was actually read
        display_type = self.get_display_type_by_extension(read_path_str)

        # If the read path was a generated .md (from PDF cache), force TEXT or MARKDOWN display type
        if read_path_str.endswith('.md') and original_file_path_str.endswith('.pdf'):
             display_type = DisplayType.TEXT # Or potentially a specific MARKDOWN type if exists
             # 或者如果存在特定的 MARKDOWN 类型，则使用它

        return ToolDetail(
            type=display_type,
            data=FileContent(
                # Show the original requested filename to the user
                # 向用户显示原始请求的文件名
                file_name=original_file_name,
                # Content is the raw content (without meta) from the read file (could be .md)
                # 内容是来自读取文件（可能是 .md）的原始内容（不含元信息）
                content=result.extra_info["raw_content"]
            )
        )

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """
        获取工具调用后的友好动作和备注
        """
        # Use the original file path requested by the user
        file_path_str = arguments.get("file_path", "")
        file_name = os.path.basename(file_path_str) if file_path_str else "文件"

        if not result.ok:
            # Keep error reporting simple, using the original file name
            # 使用原始文件名保持错误报告简洁
            return {
                "action": "读取文件",
                "remark": f"读取「{file_name}」失败: {result.error or result.content}" # Use error if available
                # 如果有错误信息则使用，否则使用 content
            }

        # Success message always refers to the original requested file
        # 成功消息始终引用原始请求的文件
        return {
            "action": "读取文件",
            "remark": f"「{file_name}」"
        }

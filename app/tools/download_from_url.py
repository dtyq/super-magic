import os
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional

import aiofiles
import aiohttp
from pydantic import Field

from agentlang.context.tool_context import ToolContext
from app.core.entity.message.server_message import DisplayType, FileContent, ToolDetail
from agentlang.tools.tool_result import ToolResult
from agentlang.event.event import EventType
from agentlang.logger import get_logger
from app.tools.abstract_file_tool import AbstractFileTool
from app.tools.core import BaseToolParams, tool
from app.tools.workspace_guard_tool import WorkspaceGuardTool
from agentlang.utils.file import generate_safe_filename

logger = get_logger(__name__)


class DownloadFromUrlParams(BaseToolParams):
    """从URL下载文件参数"""
    url: str = Field(
        ...,
        description="要下载的文件URL地址，支持HTTP和HTTPS协议"
    )
    file_path: str = Field(
        ...,
        description="保存文件的路径和文件名，相对于工作区根目录。例如，要保存到工作区的 `webview_reports` 目录下并命名为 `file.txt`，请传入 `webview_reports/file.txt`。建议使用清晰的文件名（例如 `年度报告.pdf`）便于查找。如果指定的目录不存在，会自动创建。"
    )
    override: bool = Field(
        False,
        description="如果文件已存在，是否覆盖"
    )

    @classmethod
    def get_custom_error_message(cls, field_name: str, error_type: str) -> Optional[str]:
        """获取自定义参数错误信息"""
        if field_name == "url":
            return "缺少必要参数'url'。请提供有效的下载地址。"
        elif field_name == "file_path":
            return "缺少必要参数'file_path'。请提供文件保存路径。"
        return None


class DownloadResult(NamedTuple):
    """下载结果详情"""
    file_size: int  # 文件大小（字节）
    content_type: str  # 内容类型
    file_exists: bool  # 文件是否已存在
    file_path: str  # 文件保存路径
    url: str  # 下载的URL（可能是重定向后的URL）
    redirect_count: int  # 重定向次数


@tool()
class DownloadFromUrl(AbstractFileTool[DownloadFromUrlParams], WorkspaceGuardTool[DownloadFromUrlParams]):
    """
    URL文件下载工具

    - 支持自动处理重定向
    - 如果文件不存在，将自动创建文件和必要的目录
    - 如果文件已存在且未指定覆盖，将返回错误
    - 支持各种类型的文件下载，如图片、PDF、压缩包等
    """

    async def execute(self, tool_context: ToolContext, params: DownloadFromUrlParams) -> ToolResult:
        """
        执行文件下载操作

        Args:
            tool_context: 工具上下文
            params: 参数对象，包含URL和文件保存路径

        Returns:
            ToolResult: 包含操作结果
        """
        try:
            # 使用父类方法获取安全的文件路径对象，这会处理目录结构
            full_path, error = self.get_safe_path(params.file_path)
            if error:
                return ToolResult(error=error)

            # 从安全路径对象中提取父目录和原始文件名
            parent_dir = full_path.parent
            original_name = full_path.name

            # 分离基本名称和扩展名
            base_name, extension = os.path.splitext(original_name)

            # 对基本名称部分进行安全处理
            safe_base_name = generate_safe_filename(base_name)

            # 如果基本名称处理后为空，尝试从 URL 获取或使用默认名称
            if not safe_base_name:
                from urllib.parse import urlparse
                try:
                    parsed_url = urlparse(params.url)
                    url_filename = os.path.basename(parsed_url.path)
                    if url_filename: # 确保从URL获取的文件名不为空
                        url_base_name, url_extension = os.path.splitext(url_filename)
                        safe_base_name = generate_safe_filename(url_base_name) if url_base_name else "downloaded_file"
                        # Use the extension from the URL if available and original was missing or different
                        if url_extension and (not extension or extension.lower() != url_extension.lower()):
                            extension = url_extension
                    else:
                        safe_base_name = "downloaded_file"
                except Exception:
                    safe_base_name = "downloaded_file" # Fallback default name

            # 重新组合安全的文件名和原始扩展名
            # 确保扩展名以点开头（如果存在且不是点）
            if extension and not extension.startswith('.'):
                 extension = '.' + extension
            safe_name = safe_base_name + extension

            # 重构最终的文件路径
            file_path = parent_dir / safe_name

            # 检查文件是否存在
            file_exists = file_path.exists()

            # 如果文件已存在且不允许覆盖，返回错误信息
            if file_exists and not params.override:
                return ToolResult(
                    error=f"文件已存在，如需覆盖请设置 override=True\n"
                    f"file_path: {file_path!s}"
                )

            # 创建目录（如果需要）
            await self._create_directories(file_path)

            # 下载文件
            download_result = await self._download_file(params.url, file_path)

            # 触发文件事件
            event_type = EventType.FILE_UPDATED if download_result.file_exists else EventType.FILE_CREATED
            await self._dispatch_file_event(tool_context, str(file_path), event_type)

            # 生成格式化的输出
            output = (
                f"文件下载成功: {file_path} | "
                f"大小: {self._format_size(download_result.file_size)} | "
                f"类型: {download_result.content_type} | "
                f"重定向次数: {download_result.redirect_count}"
            )

            # 返回操作结果
            return ToolResult(content=output)

        except Exception as e:
            logger.exception(f"下载文件失败: {e!s}")
            return ToolResult(error=f"下载文件失败: {e!s}")

    async def _create_directories(self, file_path: Path) -> None:
        """创建文件所需的目录结构"""
        directory = file_path.parent

        if not directory.exists():
            os.makedirs(directory, exist_ok=True)
            logger.info(f"创建目录: {directory}")

    async def _download_file(self, url: str, file_path: Path) -> DownloadResult:
        """下载文件内容"""
        redirect_count = 0
        final_url = url
        content_type = ""
        file_exists = file_path.exists()

        async with aiohttp.ClientSession() as session:
            # 设置允许重定向并跟踪重定向次数
            async with session.get(url, allow_redirects=True) as response:
                # 检查响应状态
                if response.status != 200:
                    raise Exception(f"下载失败，HTTP状态码: {response.status}, 原因: {response.reason}")

                # 获取最终URL（如果有重定向）
                final_url = str(response.url)
                # 计算重定向次数
                if hasattr(response, 'history'):
                    redirect_count = len(response.history)

                # 获取内容类型
                content_type = response.headers.get('Content-Type', '未知类型')

                # 打开文件并写入内容
                async with aiofiles.open(file_path, 'wb') as f:
                    file_size = 0
                    # 按块读取并写入文件，避免内存问题
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)
                        file_size += len(chunk)

        logger.info(f"文件下载完成: {file_path}, 大小: {file_size} 字节")

        return DownloadResult(
            file_size=file_size,
            content_type=content_type,
            file_exists=file_exists,
            file_path=str(file_path),
            url=final_url,
            redirect_count=redirect_count
        )

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

        if not arguments or "file_path" not in arguments:
            logger.warning("没有提供file_path参数")
            return None

        file_path = arguments["file_path"]
        file_path_path, _ = self.get_safe_path(file_path)
        if not file_path_path or not file_path_path.exists():
            return None

        file_name = os.path.basename(file_path)

        # 使用 AbstractFileTool 的方法获取显示类型
        display_type = self.get_display_type_by_extension(file_path)

        # 对于图片类型，我们可能需要返回文件路径而不是内容
        # 这里简化处理，只返回文件名
        return ToolDetail(
            type=display_type,
            data=FileContent(
                file_name=file_name,
                content="" # 对于大文件或二进制文件，不返回内容
            )
        )

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """
        获取工具调用后的友好动作和备注
        """
        if not arguments:
            return {"action": "下载文件", "remark": "未知文件"}

        url = arguments.get("url", "")
        remark = url if url else "未知URL"

        return {
            "action": "下载文件",
            "remark": remark
        }

    def _format_size(self, size_bytes: int) -> str:
        """格式化文件大小显示"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0 or unit == 'TB':
                return f"{size_bytes:.2f} {unit}" if unit != 'B' else f"{size_bytes} {unit}"
            size_bytes /= 1024.0

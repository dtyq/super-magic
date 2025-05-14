import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles
import httpx
from pydantic import Field

from agentlang.config.config import config
from agentlang.context.tool_context import ToolContext
from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from agentlang.utils.file import generate_safe_filename
from app.core.entity.message.server_message import DisplayType, FileContent, ToolDetail
from app.paths import PathManager
from app.tools.abstract_file_tool import AbstractFileTool
from app.tools.core import BaseToolParams, tool
from app.tools.download_from_url import DownloadFromUrl, DownloadFromUrlParams
from app.tools.summarize import Summarize
from app.tools.workspace_guard_tool import WorkspaceGuardTool
from app.utils.pdf_converter_utils import convert_pdf_locally

logger = get_logger(__name__)

# 保存 Markdown 结果的目录
DEFAULT_RECORDS_DIR_NAME = "webview_reports"

def get_or_create_records_dir(dir_name: str = DEFAULT_RECORDS_DIR_NAME) -> Path:
    """获取或创建记录目录"""
    records_dir = PathManager.get_workspace_dir() / dir_name
    records_dir.mkdir(parents=True, exist_ok=True)
    return records_dir

def is_safe_path(base_path: Path, target_path_str: str) -> bool:
    """检查目标路径是否在基础路径下且安全"""
    try:
        # 使用 resolve() 来处理 '..' 等情况
        target_path = (base_path / target_path_str).resolve(strict=False) # strict=False 允许解析不存在的路径
        # 确保解析后的路径仍然在基础路径下
        return target_path.is_relative_to(base_path.resolve(strict=True))
    except Exception:
        return False

class ConvertPdfParams(BaseToolParams):
    """PDF 转换工具参数"""
    input_path: str = Field(
        ...,
        description="输入的 PDF 来源，可以是本地文件路径（相对于工作空间）或 HTTP/HTTPS URL。"
    )
    output_path: str = Field(
        "",
        description=(
            "输出的 Markdown 文件保存路径（可选，相对于工作空间）。" +
            "如果未提供：对于 URL 来源，将自动生成路径保存在 `webview_reports` 目录下；" +
            "(未来计划)对于本地文件来源，将保存在源文件相同目录下，同名但扩展名为 .md。"
        )
    )
    mode: str = Field(
        "smart", # 默认为智能模式
        description="转换模式：'smart' (使用外部智能API处理URL，质量可能更高但较慢) 或 'normal' (使用本地库处理本地文件和URL，速度更快)。如果输入是本地文件，将强制使用 'normal' 模式。"
    )
    override: bool = Field(
        True,
        description="当输出文件已存在时，是否覆盖。仅在指定了 `output_path` 时生效。"
    )

@tool()
class ConvertPdf(AbstractFileTool[ConvertPdfParams], WorkspaceGuardTool[ConvertPdfParams]):
    """
    PDF 转换工具，将指定的 PDF 文件（本地路径或 URL）转换为 Markdown 格式。

    可以指定输出 Markdown 文件的保存路径（相对于工作空间），如果不指定，将自动处理。

    适用于：
    - 将在线 PDF 文档转换为 Markdown 格式以便阅读或进一步处理。
    - 提取 PDF 中的文本和基本结构。

    支持模式:
    - **smart (默认)**: 使用外部智能 API 处理 URL。可能提供更高质量的转换结果，但仅支持 URL 且可能较慢。
    - **normal**: 使用内置库进行转换。支持本地文件和 URL，速度较快，但对于复杂或扫描版 PDF 效果可能不如 smart 模式。

    要求：
    - 输入 PDF 的路径 (`input_path`)，可以是工作区相对路径或 URL。
    - （可选）转换模式 (`mode`)，默认为 'smart'。如果 `input_path` 是本地文件，将强制使用 'normal' 模式。
    - （可选）提供一个安全的工作空间相对路径 (`output_path`) 用于保存 Markdown 文件。如果不提供，将自动生成路径。
    - （可选）是否覆盖已存在的文件 (`override`)，默认为 true。仅在提供了 `output_path` 时有效。

    调用示例：
    ```
    {
        "input_path": "documents/report.pdf", // 本地文件
        "output_path": "webview_reports/converted_report.md"
    }
    ```
    ```
    {
        "input_path": "https://example.com/report.pdf",
        "output_path": "webview_reports/converted_report.md"
    }
    ```
    或者不指定输出路径：
    ```
    {
        "input_path": "https://another.example.com/document.pdf",
        "mode": "normal" // 使用本地库转换 URL
    }
    ```
    ```
    {
        "input_path": "local_files/mydoc.pdf" // 本地文件，自动使用 normal 模式
    }
    ```
    """

    async def execute(
        self,
        tool_context: ToolContext,
        params: ConvertPdfParams
    ) -> ToolResult:
        """执行 PDF 转换。"""
        return await self.execute_purely(params)

    async def execute_purely(
        self,
        params: ConvertPdfParams
    ) -> ToolResult:
        """执行 PDF 转换的核心逻辑，无需上下文。"""
        workspace_root = PathManager.get_workspace_dir()
        input_location = params.input_path
        target_output_path_str = params.output_path
        user_mode = params.mode.lower()
        override_output = params.override

        # --- 1. 确定输入类型和有效模式 ---
        is_url = bool(re.match(r'^https?://', input_location))
        effective_mode = user_mode
        pdf_source_path: Optional[Path] = None # 将用于 normal 模式处理的源文件路径
        temp_download_path: Optional[Path] = None # normal 模式下 URL 下载的临时路径

        try:
            if not is_url:
                logger.info(f"输入 '{input_location}' 被识别为本地路径，强制使用 'normal' 模式。")
                effective_mode = "normal"
                # 验证本地路径安全
                safe_path, error = self.get_safe_path(input_location)
                if error:
                    return ToolResult(error=error)
                if not await aiofiles.os.path.exists(safe_path) or await aiofiles.os.path.isdir(safe_path):
                    return ToolResult(error=f"本地文件不存在或不是文件：'{input_location}'")
                pdf_source_path = safe_path
            elif effective_mode == "normal":
                # URL 输入，但指定了 normal 模式，需要先下载
                logger.info(f"URL 输入 '{input_location}'，使用 'normal' 模式，将先下载文件。")
                # 此处需要调用 DownloadFromUrl
                pass # 下载逻辑将在后面实现
            elif effective_mode != "smart":
                 return ToolResult(error=f"无效的模式 '{params.mode}'。请选择 'smart' 或 'normal'。")

            logger.info(f"执行 PDF 转换: 输入='{input_location}', 模式='{effective_mode}', 输出到='{target_output_path_str or '自动处理'}'")

            markdown_content: Optional[str] = None
            final_output_path: Optional[Path] = None # 最终保存 Markdown 的绝对路径

            # --- 2. 执行转换 (根据模式分发) ---
            if effective_mode == "smart":
                # 智能模式：调用外部 API (仅支持 URL)
                if not is_url:
                    # 理论上不会到这里，因为本地文件会强制 normal
                    return ToolResult(error="内部错误：Smart 模式不应用于本地文件。")

                # 获取 API 配置
                api_key = config.get("pdf_understanding.api_key")
                api_url = config.get("pdf_understanding.api_url")
                if not api_key or not api_url:
                    return ToolResult(error="智能 PDF 转换服务未配置，请联系管理员。")

                headers = { "api-key": api_key, "Content-Type": "application/json" }
                payload = { "message": input_location, "conversation_id": "" }
                try:
                    async with httpx.AsyncClient(timeout=config.get("llm.api_timeout", 600)) as client:
                        response = await client.post(api_url, headers=headers, json=payload)
                        response.raise_for_status()
                    response_data = response.json()
                except httpx.HTTPStatusError as e:
                    logger.exception(f"智能 PDF 转换 API 请求失败: 状态码={e.response.status_code}, 响应={e.response.text}")
                    return ToolResult(error="智能 PDF 转换失败，与处理服务通信时出错。")
                except httpx.RequestError as e:
                    logger.exception(f"智能 PDF 转换 API 请求无法发送: {e}")
                    return ToolResult(error="智能 PDF 转换失败，无法连接到处理服务。")

                # 解析 API 响应
                # --- API Response Parsing START ---
                if response_data.get("code") == 1000:
                    try:
                        content = response_data["data"]["messages"][0]["message"]["content"]
                        markdown_content = content if content else "<!-- PDF 已处理（智能模式），但未提取到有效内容 -->"
                        logger.info("Smart 模式 API 调用成功并提取内容。")
                    except (KeyError, IndexError, TypeError) as e:
                        logger.error(f"解析智能 PDF 转换 API 响应结构失败: {e}, 响应: {response_data}")
                        return ToolResult(error="未能成功解析智能 PDF 处理服务的响应。")
                else:
                    error_message = response_data.get("message", "未知的 API 错误")
                    logger.error(f"智能 PDF 转换 API 错误: code={response_data.get('code')}, message={error_message}, 响应: {response_data}")
                    return ToolResult(error="智能 PDF 转换失败，处理服务返回错误。")
                # --- API Response Parsing END ---

            elif effective_mode == "normal":
                # 普通模式：使用本地库 (支持本地文件和已下载的 URL)

                if is_url:
                    # --- 下载 URL ---
                    download_tool = DownloadFromUrl()
                    # 创建临时下载目录
                    temp_dir = workspace_root / ".cache" / "pdf_downloads"
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    # 生成临时文件名
                    base_name = self._extract_source_name(input_location)
                    safe_base_name = generate_safe_filename(base_name) or "downloaded_pdf"
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    temp_pdf_filename = f"{safe_base_name}_{timestamp}.pdf"
                    temp_download_path = temp_dir / temp_pdf_filename

                    logger.info(f"Normal 模式下载 URL '{input_location}' 到临时文件 '{temp_download_path}'")
                    download_params = DownloadFromUrlParams(
                        url=input_location,
                        # 提供相对于工作区的路径给下载工具
                        file_path=str(temp_download_path.relative_to(workspace_root)),
                        override=True # 覆盖同名临时文件
                    )
                    download_result = await download_tool.execute_purely(download_params)
                    if not download_result.ok:
                        logger.error(f"Normal 模式下载 PDF 失败: {download_result.error}")
                        return ToolResult(error=f"下载 PDF 文件失败: {download_result.error}")
                    pdf_source_path = temp_download_path # 更新源路径为下载的文件
                    logger.info(f"PDF 已成功下载到: {pdf_source_path}")
                    # --- 下载结束 ---

                # --- 调用本地转换 ---
                if not pdf_source_path or not await aiofiles.os.path.exists(pdf_source_path):
                    return ToolResult(error="内部错误：无法找到用于本地转换的源 PDF 文件。")

                logger.info(f"Normal 模式调用本地转换获取文本: {pdf_source_path}")
                # 直接获取 Markdown 文本内容
                markdown_content = await convert_pdf_locally(pdf_source_path)

                if markdown_content is None:
                    logger.error(f"Normal 模式本地转换失败: {pdf_source_path}")
                    return ToolResult(error=f"使用本地库转换 PDF 文件 '{pdf_source_path.name}' 失败。")

                logger.info("Normal 模式本地转换成功，已获取 Markdown 文本。")
                # 在 normal 模式下，md_cache_path 是潜在的输出文件之一
                # 如果用户未指定 output_path，我们就用它

            # --- 3. 检查转换结果 ---
            # 经过 smart 或 normal 模式处理后，检查 markdown_content 是否有值
            if markdown_content is None: # Sanity check, should have been caught above
                logger.error(f"未能成功获取 Markdown 内容 (模式: {effective_mode})，输入: {input_location}")
                #返回更具体的错误信息
                return ToolResult(error=f"PDF 转换失败（模式: {effective_mode}），未能获取有效内容。")

            # --- 4. 生成摘要 ---
            pdf_source_name = self._extract_source_name(input_location)
            summary = "无法生成摘要。"
            try:
                summarizer = Summarize()
                generated_summary = await summarizer.summarize_content(
                    content=markdown_content,
                    title=pdf_source_name,
                    max_length=500
                )
                if generated_summary:
                    summary = generated_summary
                else:
                     logger.warning(f"为 PDF '{pdf_source_name}' 生成摘要失败（返回空），将使用默认提示。")
            except Exception as summary_e:
                logger.error(f"为 PDF '{pdf_source_name}' 生成摘要时发生异常: {summary_e}", exc_info=True)

            # --- 5. 确定保存路径并保存文件 ---
            workspace_root = PathManager.get_workspace_dir()
            saved_file_relative_path: Optional[str] = None

            try:
                if target_output_path_str:
                    # 用户指定了路径
                    safe_output_path, error = self.get_safe_path(target_output_path_str)
                    if error:
                         logger.error(f"指定的输出路径不安全或在工作空间之外: {target_output_path_str}")
                         return ToolResult(error=f"指定的输出路径 '{target_output_path_str}' 不安全或无效: {error}")

                    # 检查文件是否存在以及是否允许覆盖
                    if await aiofiles.os.path.exists(safe_output_path) and not override_output:
                         logger.warning(f"输出文件已存在且不允许覆盖: {safe_output_path}")
                         return ToolResult(error=f"输出文件 '{target_output_path_str}' 已存在。如需覆盖请设置 override=True。")

                    # 确保父目录存在
                    safe_output_path.parent.mkdir(parents=True, exist_ok=True)
                    final_output_path = safe_output_path

                else:
                    # 用户未指定输出路径，统一生成在 webview_reports
                    # if effective_mode == "normal":
                    #     # Normal 模式下，如果没有指定输出，结果就是 cache 文件
                    #     if not md_cache_path: # Sanity check
                    #          return ToolResult(error="内部错误：无法确定 normal 模式的默认输出路径。")
                    #     final_output_path = md_cache_path
                    #     logger.info(f"Normal 模式未指定输出路径，将使用缓存文件: {final_output_path}")
                    #
                    # elif effective_mode == "smart":
                    #     # Smart 模式 (必然是 URL 来源)，保存在 webview_reports
                    #     if not is_url: # Sanity check
                    #         return ToolResult(error="内部错误：Smart 模式应只处理 URL。")
                    #
                        # 新逻辑：所有默认输出都放入 webview_reports
                        logger.info("未指定输出路径，将在 webview_reports 中自动生成文件名。")
                        records_dir = get_or_create_records_dir()
                        safe_filename_base = generate_safe_filename(pdf_source_name) or "pdf_content"
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        filename = f"{safe_filename_base}_{timestamp}.md"
                        saved_file_absolute_path = records_dir / filename
                        final_output_path = records_dir / filename

                # 确定相对路径
                saved_file_relative_path = str(final_output_path.relative_to(workspace_root))

                # 执行唯一一次写入操作
                async with aiofiles.open(final_output_path, "w", encoding="utf-8") as f:
                    await f.write(markdown_content)
                logger.info(f"转换结果已写入到最终目标文件: {saved_file_relative_path}")

            except OSError as write_e:
                output_path_display = final_output_path or target_output_path_str or "未知路径"
                logger.error(f"保存 Markdown 文件失败: {output_path_display}, 错误: {write_e}", exc_info=True)
                return ToolResult(
                    error=f"成功转换 PDF，但保存 Markdown 文件到 '{saved_file_absolute_path}' 时出错: {write_e}。转换后的内容在 extra_info 中。",
                    extra_info={
                        "pdf_source_name": pdf_source_name,
                        "saved_file_path": None,
                        "full_content": markdown_content,
                    }
                )
            except Exception as e:
                logger.error(f"确定或创建保存路径时发生意外错误: {e}", exc_info=True)
                return ToolResult(error="处理文件保存路径时发生内部错误。")

            # --- 6. 构建返回结果 ---
            ai_content = f"**PDF 内容摘要**:\n{summary}"
            if saved_file_relative_path:
                ai_content += f"\n\n**提示**: 完整的 PDF 内容已处理（模式: {effective_mode}）并保存至 `{saved_file_relative_path}`。如需详细信息，请使用 `read_file` 工具读取此文件。"
            else:
                ai_content += "\n\n**警告**: 完整内容已转换但未能成功保存到文件，无法通过 `read_file` 访问。"

            result = ToolResult(
                content=ai_content,
                extra_info={
                    "pdf_source_name": pdf_source_name,
                    "saved_file_path": saved_file_relative_path,
                    "full_content": markdown_content,
                }
            )
            return result

        except Exception as e:
            logger.exception(f"PDF 转换操作意外失败: {e!s}")
            return ToolResult(error="执行 PDF 转换时发生未预料的内部错误。")
        finally:
             # --- 清理下载的临时文件 ---
             if temp_download_path and await aiofiles.os.path.exists(temp_download_path):
                 try:
                     await aiofiles.os.remove(temp_download_path)
                     logger.info(f"已清理临时下载文件: {temp_download_path}")
                 except OSError as remove_e:
                     logger.warning(f"清理临时下载文件失败 {temp_download_path}: {remove_e}")

    async def get_tool_detail(self, tool_context: ToolContext, result: ToolResult, arguments: Dict[str, Any] = None) -> Optional[ToolDetail]:
        """生成工具详情，用于前端展示"""
        try:
            full_content = result.extra_info.get("full_content")
            saved_file_path = result.extra_info.get("saved_file_path")
            pdf_source_name = result.extra_info.get("pdf_source_name", "未知来源")

            if not full_content:
                logger.error("无法生成工具详情：extra_info 中 full_content 缺失或为空。")
                return None # 核心内容缺失

            # 确定显示的文件名
            if saved_file_path:
                display_filename = Path(saved_file_path).name # 从相对路径获取文件名
            else:
                 # 如果保存失败，生成一个临时的名字
                 safe_filename_base = generate_safe_filename(pdf_source_name) or "converted_pdf"
                 display_filename = f"转换结果_{safe_filename_base}.md"
                 logger.warning(f"Tool detail: saved_file_path 为空，使用备用文件名: {display_filename}")


            return ToolDetail(
                type=DisplayType.MD,
                data=FileContent(
                    file_name=display_filename,
                    content=full_content
                )
            )
        except Exception as e:
            logger.error(f"生成工具详情时发生意外错误: {e}", exc_info=True)
            return None

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """获取工具调用后的友好动作和备注"""
        pdf_source_name = "PDF文档"
        if result.extra_info and "pdf_source_name" in result.extra_info:
            pdf_source_name = result.extra_info["pdf_source_name"]
        elif arguments and "input_path" in arguments: # 使用 input_path
             pdf_source_name = self._extract_source_name(arguments["input_path"])

        remark = f"已转换 PDF: {pdf_source_name}"
        if result.ok and result.extra_info and result.extra_info.get("saved_file_path"):
            remark += f"，保存至 `{result.extra_info['saved_file_path']}`"
        elif result.error:
             remark += " (但处理或保存中遇到问题)"

        return {
            "action": "PDF转换",
            "remark": remark
        }

    def _extract_source_name(self, source_location_url: str) -> str:
        """从 PDF 来源 URL 提取用于显示的文件名"""
        try:
            parsed_url = urllib.parse.urlparse(source_location_url)
            path_part = parsed_url.path
            file_name = path_part.split('/')[-1]
            decoded_name = urllib.parse.unquote(file_name)
            base_name = decoded_name.split('?')[0]
            return base_name if base_name and base_name != '/' else "网络PDF文档"
        except Exception as e:
            logger.warning(f"从 URL '{source_location_url}' 提取文件名失败: {e}", exc_info=False)
            return "网络PDF文档"

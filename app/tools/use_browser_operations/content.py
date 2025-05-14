"""浏览器内容读取操作组

包含页面内容读取、转换等操作
"""

import datetime
import os
from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import Field

from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from agentlang.utils.file import generate_safe_filename_with_timestamp
from app.paths import PathManager
from app.tools.purify import Purify
from app.tools.summarize import Summarize
from app.tools.use_browser_operations.base import BaseOperationParams, OperationGroup, operation
from app.tools.visual_understanding import VisualUnderstanding, VisualUnderstandingParams
from magic_use.magic_browser import (
    MagicBrowser,
    MagicBrowserError,
    MarkdownSuccess,
    PageStateSuccess,
    ScreenshotSuccess,
)

# 日志记录器
logger = get_logger(__name__)

# 定义markdown记录目录名称
MARKDOWN_RECORDS_DIR_NAME = "webview_reports"
# 定义markdown_records目录路径但不立即创建
MARKDOWN_RECORDS_DIR = PathManager.get_workspace_dir() / MARKDOWN_RECORDS_DIR_NAME

def get_or_create_markdown_records_dir() -> Path:
    """确保markdown记录目录存在并返回该目录路径

    Returns:
        Path: markdown记录目录的路径
    """
    MARKDOWN_RECORDS_DIR.mkdir(exist_ok=True)
    return MARKDOWN_RECORDS_DIR


def _add_markdown_metadata(content: str, title: str, url: str, scope: str, current_screen: Optional[int] = None, summary: Optional[str] = None) -> str:
    """向Markdown内容添加元数据头

    Args:
        content: 原始Markdown内容
        title: 网页标题
        url: 网页URL
        scope: 读取范围 ('viewport' 或 'all')
        current_screen: 当前屏幕编号 (仅当 scope 为 'viewport' 时有效)
        summary: 网页内容摘要 (可选)


    Returns:
        str: 添加了元数据头的Markdown内容
    """
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 构建元数据头，摘要部分设为可选
    header_lines = [
        f"# {title}",
        "",
        "> 此 Markdown 文件由超级麦吉从网页内容转换生成",
        f"> 转换时间: {now}",
        f"> 网页链接: [{url}]({url})",
        f"> 内容范围: {scope}{f' (第 {current_screen} 屏)' if scope == 'viewport' and current_screen is not None else ''}"
    ]
    if summary: # 仅在提供了摘要时添加摘要行
        header_lines.append(f"> 内容摘要: {summary}")
    header_lines.extend([
        "",
        "## 原始内容",
        ""
    ])

    header = "\n".join(header_lines)
    return header + content


class ReadAsMarkdownParams(BaseOperationParams):
    """读取页面为Markdown的参数"""
    scope: Literal["viewport", "all"] = Field("viewport", description="内容范围: viewport (当前视口) 或 all (整个页面)")
    purify: Union[bool, str] = Field(False, description="是否净化网页内容以及使用的标准。False: 不净化；True: 使用通用标准净化；字符串: 使用该字符串作为自定义净化标准。净化会尝试移除广告、导航等无关信息，但可能误删部分有效内容。推荐在提取文章/新闻正文时使用。")


class VisualQueryParams(BaseOperationParams):
    """视觉查询参数"""
    query: str = Field(..., description="关于当前页面截图的问题或分析要求")


class ContentOperations(OperationGroup):
    """内容操作组

    包含页面内容读取、转换等操作
    """
    group_name = "content"
    group_description = "页面内容读取相关操作"

    @operation(
        example=[
            {
                "operation": "read_as_markdown",
                "operation_params": {
                    "scope": "viewport"
                }
            },
            {
                "operation": "read_as_markdown",
                "operation_params": {
                    "scope": "all"
                }
            },
            {
                "operation": "read_as_markdown",
                "operation_params": {
                    "scope": "all",
                    "purify": "只保留正文内容" # 使用自定义标准净化
                }
            }
        ]
    )
    async def read_as_markdown(self, browser: MagicBrowser, params: ReadAsMarkdownParams) -> ToolResult:
        """将网页内容读取为 Markdown 格式。

        可以获取网页中的所有内容，包括文本、链接、图片等。但图片只只能获取链接，若想要理解图片内容，请使用 visual_query 工具配合 scroll_to 逐步分析网页。

        `scope` 参数 (默认为 `viewport`):
        - `viewport`: 只获取当前视口内的内容，直接返回完整内容。
        - `all`: 获取整个页面的内容，只返回摘要信息，完整内容自动保存到工作目录的 webview_reports 目录下，你需要在必要时通过读取自动保存的文件来获取完整的网页内容，但这个操作非常昂贵。

        `purify` 参数 (默认为 `false`):
        - `true`: 使用默认通用标准尝试净化内容，移除广告、导航、页脚等非正文元素。有助于提取核心文章，但有误删风险。
        - `false`: 保留网页原始内容结构，不进行净化。
        - `字符串`: 将该字符串作为自定义标准进行净化，例如 "保留文章主体，移除相关推荐"。

        请避免重复相同的参数使用该操作，否则会保存大量重复的文件。
        """
        # 1. 获取并验证页面
        _, error_result = await self._get_validated_page(browser, params)
        if error_result: return error_result
        page_id = params.page_id or await browser.get_active_page_id()
        if not page_id:
            return ToolResult(error="无法确定要读取的页面ID")

        # 2. 调用 MagicBrowser 的 read_as_markdown 方法
        try:
            result = await browser.read_as_markdown(page_id=page_id, scope=params.scope)

            # 3. 处理返回结果
            if isinstance(result, MagicBrowserError):
                return ToolResult(error=result.error)
            elif isinstance(result, MarkdownSuccess):
                # 提取数据
                markdown_text = result.markdown
                url = result.url
                title = result.title
                scope = result.scope

                # 根据参数决定是否调用净化方法
                purification_applied = False
                purification_criteria = None
                if params.purify is not False: # 如果不是明确的 False，则尝试净化
                    if isinstance(params.purify, str):
                        purification_criteria = params.purify
                        logger.info(f"请求使用自定义标准净化 Markdown 内容: '{purification_criteria}'")
                    else: # params.purify is True
                        logger.info("请求使用通用标准净化 Markdown 内容...")

                    purified_markdown = await self._purify_content(markdown_text, criteria=purification_criteria)
                    if purified_markdown != markdown_text: # 仅在内容确实被修改时标记为已净化
                        markdown_text = purified_markdown
                        purification_applied = True
                        logger.info("Markdown 内容已净化。")
                    else:
                        logger.info("Markdown 内容无需净化或净化失败/未改变，使用原始内容。")
                else:
                    logger.info("跳过 Markdown 内容净化步骤 (purify=False)。")

                # 修改：仅在 scope 为 'all' 时生成摘要
                summary = None
                if scope == "all":
                    summary = await self._generate_summary(title, markdown_text)

                # --- 文件名生成逻辑 (保持不变) ---
                records_dir = get_or_create_markdown_records_dir()
                safe_title = generate_safe_filename_with_timestamp(title)
                filename_suffix = scope # 默认为 "all" 或 "viewport"
                current_screen_for_metadata: Optional[int] = None # 用于传递给 metadata 函数

                # 如果是读取视口，尝试获取当前屏幕编号
                if scope == "viewport":
                    try:
                        page_state_result = await browser.get_page_state(page_id=page_id)
                        if isinstance(page_state_result, PageStateSuccess) and page_state_result.state.position_info:
                            current_screen = int(page_state_result.state.position_info.current_screen)
                            filename_suffix = f"part{current_screen}" # 使用 part{n}
                            current_screen_for_metadata = current_screen # 保存屏幕编号用于元数据
                            logger.info(f"获取到当前屏幕编号: {current_screen}，文件名后缀设为: {filename_suffix}")
                        else:
                            logger.warning(f"无法获取页面 {page_id} 的屏幕编号，文件名将使用默认后缀 'viewport'")
                            filename_suffix = "viewport" # 获取失败则回退
                    except Exception as state_exc:
                        logger.warning(f"获取页面 {page_id} 状态以确定屏幕编号时出错: {state_exc!s}，文件名将使用默认后缀 'viewport'")
                        filename_suffix = "viewport" # 异常时回退

                # 使用确定的后缀构建文件名
                filename = f"{safe_title}_{filename_suffix}.md"
                # --- 文件名生成逻辑结束 ---

                file_path = records_dir / filename
                # 修改：在调用 _add_markdown_metadata 时，根据 scope 决定是否传入 summary
                markdown_text_with_metadata = _add_markdown_metadata(
                    content=markdown_text, # 参数名改为 content
                    title=title,
                    url=url,
                    scope=scope,
                    current_screen=current_screen_for_metadata,
                    summary=summary # summary 可能是 None
                )
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(markdown_text_with_metadata)
                    relative_path = os.path.join(MARKDOWN_RECORDS_DIR_NAME, filename)
                except Exception as write_e:
                    logger.error(f"保存 Markdown 文件失败: {file_path}, 错误: {write_e}", exc_info=True)
                    return ToolResult(error=f"保存 Markdown 文件失败: {write_e}")

                # 修改：根据 scope 格式化不同的成功结果
                markdown_result_header = (
                    f"**操作: read_as_markdown**\n"
                    f"状态: 成功 ✓\n"
                    f"范围: {scope}{f' (第 {current_screen} 屏)' if scope == 'viewport' and filename_suffix.startswith('part') else ''}\n" # 在结果中也显示屏号
                    f"是否净化: {'是' if purification_applied else '否'}"
                )
                if purification_applied:
                    markdown_result_header += f" (标准: {'通用' if purification_criteria is None else f'自定义 - {purification_criteria}'})"
                markdown_result_header += f"{' 注意: 净化可能会误删除部分有价值信息' if purification_applied else ''}\n"
                markdown_result_header += (
                    f"标题: {title}\n"
                    f"保存路径: `{relative_path}`\n"
                )

                if scope == "all":
                    # scope 为 'all' 时，包含摘要和提示
                    markdown_result_content = f"\n**内容摘要**:\n{summary}" # summary 在此肯定有值
                    markdown_result_tip = "\n\n**提示**: 已成功读取**整个页面**的内容并保存至文件，你可以通过读取该文件来获取详细的页面内容。"
                    markdown_result = markdown_result_header + markdown_result_content + markdown_result_tip
                else: # scope 为 'viewport'
                    # scope 为 'viewport' 时，包含完整内容和提示
                    markdown_result_content = f"\n**内容详情**:\n{markdown_text}" # 直接使用 markdown_text
                    screen_info = f" (第 {current_screen} 屏)" if 'current_screen' in locals() and current_screen is not None else ""
                    markdown_result_tip = f"\n\n**提示**: 已成功读取**当前视口{screen_info}**的内容并保存至文件。如需获取页面其他部分内容，请使用滚动操作（如 `scroll_down`）后再次读取，或使用 `scope: all` 参数一次性读取整个页面。"
                    markdown_result = markdown_result_header + markdown_result_content + markdown_result_tip

                return ToolResult(content=markdown_result)
            else:
                logger.error(f"read_as_markdown 操作返回了未知类型: {type(result)}")
                return ToolResult(error="read_as_markdown 操作返回了意外的结果类型。")

        except Exception as e:
            logger.error(f"read_as_markdown 外部处理失败: {e!s}", exc_info=True)
            return ToolResult(error=f"读取Markdown时发生意外错误: {e!s}")

    @operation(
        example=[{
            "operation": "visual_query",
            "operation_params": {
                "query": "请描述当前网页的页面风格和配色方案"
            },
            "operation": "visual_query",
            "operation_params": {
                "query": "请用结构化的 Markdown 文本提取当前网页中文章图片里的内容"
            }
        }]
    )
    async def visual_query(self, browser: MagicBrowser, params: VisualQueryParams) -> ToolResult:
        """使用视觉理解能力分析当前网页的视口内的内容，可配合 scroll_to 逐步分析整个网页的布局、风格、元素特征等，也可以用于理解有大量图片元素的网站。但由于是视觉分析，无法获取网页中的链接的 URL 信息，如有需要请使用 read_as_markdown 或 get_interactive_elements。
        """
        # 1. 获取并验证页面
        page, error_result = await self._get_validated_page(browser, params)
        if error_result: return error_result
        page_id = params.page_id or await browser.get_active_page_id()
        if not page_id:
            return ToolResult(error="无法确定要进行视觉查询的页面ID")

        logger.info(f"开始视觉查询: 页面={page_id}, 查询='{params.query}'")

        try:
            # 2. 截图 (默认截取当前视口，由 MagicBrowser 处理临时文件)
            logger.info(f"请求截取页面 {page_id} 的屏幕截图用于视觉查询...")
            # 强制使用临时文件进行截图
            screenshot_result = await browser.take_screenshot(page_id=page_id, path=None, full_page=False)

            if isinstance(screenshot_result, MagicBrowserError):
                logger.error(f"视觉查询截图失败: {screenshot_result.error}")
                return ToolResult(error=f"视觉查询准备截图失败: {screenshot_result.error}")
            elif not isinstance(screenshot_result, ScreenshotSuccess):
                logger.error(f"take_screenshot 返回未知类型: {type(screenshot_result)}")
                return ToolResult(error="截图操作返回意外结果类型。")

            screenshot_path = screenshot_result.path
            # 临时文件现在由 MagicBrowser 管理，这里不需要再关心 is_temp
            logger.info(f"视觉查询截图成功，路径: {screenshot_path}")

            # 3. 调用视觉理解工具
            visual_understanding = VisualUnderstanding()
            vision_params = VisualUnderstandingParams(images=[str(screenshot_path)], query=params.query)
            logger.info(f"向视觉模型发送查询: {params.query}")
            vision_result = await visual_understanding.execute_purely(params=vision_params)

            if not vision_result.ok:
                error_msg = vision_result.content or "视觉模型执行失败"
                logger.error(f"视觉理解失败: {error_msg}")
                return ToolResult(error=f"视觉理解失败: {error_msg}")

            # 4. 格式化成功结果
            analysis_content = vision_result.content
            markdown_content = (
                f"**操作: visual_query**\n"
                f"状态: 成功 ✓\n"
                f"页面ID: {page_id}\n"
                f"查询: '{params.query}'\n\n"
                f"**分析结果**:\n{analysis_content}\n"
            )
            logger.info(f"视觉查询成功，页面: {page_id}, 查询: '{params.query}'")
            # 返回截图路径作为附件，方便前端展示分析依据
            return ToolResult(content=markdown_content, attachments=[str(screenshot_path)])

        except Exception as e:
            logger.exception(f"视觉查询操作中发生未预期的错误: {e!s}")
            return ToolResult(error=f"视觉查询时发生内部错误: {e!s}")

    async def _purify_content(self, original_content: str, criteria: Optional[str] = None) -> str:
        """尝试净化给定的文本内容。

        Args:
            original_content: 需要净化的原始文本。
            criteria: 可选的自定义净化标准字符串。如果为 None，则使用通用标准。

        Returns:
            str: 净化后的文本内容；如果净化失败或结果为空，则返回原始文本。
        """
        purifier = Purify()
        try:
            log_msg = "开始使用通用标准净化 Markdown 内容"
            if criteria:
                log_msg = f"开始使用自定义标准净化 Markdown 内容: '{criteria}'"
            logger.info(log_msg)

            purified_markdown = await purifier._get_purified_content(
                original_content=original_content,
                criteria=criteria, # 传递 criteria 参数
            )

            if purified_markdown is not None:
                # 检查净化结果是否为空
                if not purified_markdown.strip():
                    logger.warning("净化后的 Markdown 内容为空，可能原文全是无关内容。将使用原始文本。")
                    return original_content # 返回原文
                else:
                    logger.info("Markdown 内容净化成功")
                    return purified_markdown # 返回净化后的内容
            else:
                logger.warning("Markdown 内容净化失败或未返回有效结果。将使用原始文本。")
                return original_content # 返回原文

        except Exception as purify_exc:
            logger.warning(f"净化 Markdown 内容时发生错误: {purify_exc!s}. 将使用原始文本。", exc_info=True)
            return original_content # 异常时也返回原文

    async def _generate_summary(self, title: str, content: str) -> str:
        """生成内容摘要

        Args:
            title: 网页标题
            content: 网页内容

        Returns:
            str: 生成的摘要
        """
        try:
            # 使用摘要工具生成摘要
            summarizer = Summarize()
            # 确保传入合适的参数格式
            summary_content = await summarizer.summarize_content(content=content, title=title, max_length=300)
            if summary_content:
                return summary_content
            else:
                logger.warning("生成摘要失败")
                return "(摘要生成失败)"
        except Exception as e:
            logger.error(f"生成摘要时发生异常: {e!s}", exc_info=True)
            return "(摘要生成时出错)"

"""浏览器导航操作组

包含页面导航、滚动等操作
"""

import os
from typing import Tuple
from urllib.parse import urlparse

from pydantic import Field

from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from app.tools.use_browser_operations.base import BaseOperationParams, OperationGroup, operation
from magic_use.magic_browser import GotoSuccess, MagicBrowser, MagicBrowserError, ScrollToSuccess

# 日志记录器
logger = get_logger(__name__)

# 导航操作参数模型

class GotoParams(BaseOperationParams):
    """导航到指定URL的参数"""
    url: str = Field(..., description="URL to navigate to")


# Define ScrollToParams for scroll_to operation
class ScrollToParams(BaseOperationParams):
    """滚动到指定屏幕位置的参数"""
    screen_number: int = Field(..., description="目标屏幕编号 (从1开始)", ge=1)


class NavigationOperations(OperationGroup):
    """导航操作组

    包含页面导航、滚动等操作
    """
    group_name = "navigation"
    group_description = "页面导航相关操作"

    def _get_document_suggestion(self, url: str) -> str:
        """获取文档类型建议

        分析URL，如果是文档类型，返回相应的建议
        """
        # 优雅地解析URL和文件扩展名
        parsed_url = urlparse(url)
        path = parsed_url.path
        _, ext = os.path.splitext(path)
        ext = ext.lower()

        # 定义需要直接下载的文档类型列表
        document_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']

        if ext in document_extensions:
            doc_type = ext[1:].upper()  # 去掉点号，转为大写
            return f"对于{doc_type}文件，应当直接下载该文件而不是在浏览器中打开，否则会无法正常阅读。"

        return ""

    def _check_invalid_url(self, url: str) -> Tuple[bool, str]:
        """检测无效URL

        检查URL是否为明显无效的域名，如示例域名

        Args:
            url: 需要检查的URL

        Returns:
            Tuple[bool, str]: (是否无效, 错误信息)
        """
        # 解析URL获取域名
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()

            # 定义无效域名列表
            invalid_domains = [
                'example.com', 'example.org', 'example.net',
                'test.com', 'test.org', 'test.net',
                'domain.com', 'domain.org', 'domain.net',
                'localhost', '127.0.0.1',
                'website.com', 'mywebsite.com', 'yourwebsite.com',
                '{actual_domain}'
            ]

            # 检查是否为无效域名
            if domain in invalid_domains or domain.startswith('example.') or domain.startswith('test.'):
                return True, f"检测到无效域名: {domain}。这是一个示例域名，请使用真实的网址。"

            # 检查是否是未替换的占位符
            if '{actual_domain}' in domain:
                return True, f"检测到占位符域名: {domain}。请将{'{actual_domain}'}替换为真实的网址。"

            return False, ""
        except Exception as e:
            logger.error(f"URL检测失败: {e!s}")
            return False, ""

    @operation(
        example={
            "operation": "goto",
            "operation_params": {
                "url": "https://www.google.com"
            }
        }
    )
    async def goto(self, browser: MagicBrowser, params: GotoParams) -> ToolResult:
        """导航到指定URL

        将浏览器导航到指定的URL地址。如果未指定 page_id，将自动创建新页面。
        """
        url = params.url
        page_id_to_use = params.page_id

        # 1. 检查无效 URL
        is_invalid, error_message = self._check_invalid_url(url)
        if is_invalid:
            logger.warning(f"尝试访问无效URL: {url}")
            return ToolResult(error=error_message)

        # 2. 如果提供了 page_id，验证它 (goto 本身会处理 None page_id)
        if page_id_to_use:
            page, error_result = await self._get_validated_page(browser, params)
            if error_result: return error_result
            # 如果验证通过，page_id_to_use 保持不变

        # 3. 调用 MagicBrowser 的 goto 方法
        try:
            # browser.goto 现在负责页面创建或获取以及导航逻辑
            result = await browser.goto(page_id=page_id_to_use, url=url)

            # 4. 处理返回结果
            if isinstance(result, MagicBrowserError):
                suggestion = self._get_document_suggestion(url)
                error_msg = f"{result.error}{f' {suggestion}' if suggestion else ''}".strip()
                return ToolResult(error=error_msg)
            elif isinstance(result, GotoSuccess):
                suggestion = self._get_document_suggestion(url)
                markdown_content = (
                    f"**操作: goto**\n"
                    f"状态: 成功 ✓\n"
                    f"URL: `{result.final_url}`\n"
                    f"标题: {result.title}\n"
                )
                if suggestion:
                    markdown_content += f"\n**提示**: {suggestion}"
                return ToolResult(content=markdown_content)
            else:
                # 未知返回类型，记录错误
                logger.error(f"goto 操作返回了未知类型: {type(result)}")
                return ToolResult(error="goto 操作返回了意外的结果类型。")

        except Exception as e:
            # 兜底处理未被 MagicBrowser 捕获的异常 (理论上不应发生)
            logger.error(f"goto 外部处理失败: {e!s}", exc_info=True)
            error_msg = f"导航到 {url} 时发生意外错误: {e!s}"
            suggestion = self._get_document_suggestion(url)
            if suggestion: error_msg += f" {suggestion}"
            return ToolResult(error=error_msg)

    @operation(
        example={
            "operation": "scroll_to",
            "operation_params": {
                "screen_number": 2
            }
        }
    )
    async def scroll_to(self, browser: MagicBrowser, params: ScrollToParams) -> ToolResult:
        """滚动到指定屏幕位置

        将页面滚动到大致指定的屏幕编号处 (基于视口高度计算)。
        """
        # 1. 获取并验证页面
        page, error_result = await self._get_validated_page(browser, params)
        if error_result: return error_result
        page_id = params.page_id or await browser.get_active_page_id()
        if not page_id:
            return ToolResult(error="无法确定要滚动的页面ID")

        # 2. 调用 MagicBrowser 的 scroll_to 方法
        try:
            result = await browser.scroll_to(
                page_id=page_id,
                screen_number=params.screen_number
            )

            # 3. 处理返回结果
            if isinstance(result, MagicBrowserError):
                return ToolResult(error=result.error)
            elif isinstance(result, ScrollToSuccess):
                # 格式化成功结果
                markdown_content = (
                    f"**操作: scroll_to**\n"
                    f"状态: 成功 ✓\n"
                    f"目标屏幕: {result.screen_number}\n"
                    f"目标 Y 坐标 (估算): {result.target_y:.0f}px\n"
                    f"滚动前位置 (x,y): ({result.before.x:.0f}, {result.before.y:.0f})\n"
                    f"滚动后位置 (x,y): ({result.after.x:.0f}, {result.after.y:.0f})"
                )
                return ToolResult(content=markdown_content)
            else:
                logger.error(f"scroll_to 操作返回了未知类型: {type(result)}")
                return ToolResult(error="scroll_to 操作返回了意外的结果类型。")

        except Exception as e:
            logger.error(f"scroll_to 外部处理失败: {e!s}", exc_info=True)
            return ToolResult(error=f"滚动到屏幕 {params.screen_number} 时发生意外错误: {e!s}")

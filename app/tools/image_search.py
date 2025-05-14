import asyncio
import math
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from pydantic import Field

from agentlang.config import config
from agentlang.context.tool_context import ToolContext
from app.core.entity.message.server_message import ToolDetail, DisplayType, FileContent
from agentlang.tools.tool_result import ToolResult
from agentlang.logger import get_logger
from app.tools.core import BaseTool, BaseToolParams, tool

logger = get_logger(__name__)


class ImageSearchParams(BaseToolParams):
    """图片搜索工具参数"""
    query: str = Field(..., description="搜索关键词")
    count: int = Field(default=5, description="期望返回的图片结果数量", ge=1, le=50)


def _format_bytes(size_bytes: int) -> str:
    """将字节大小格式化为易读的字符串"""
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


def _format_iso_date(date_str: Optional[str]) -> str:
    """将 ISO 8601 格式的日期字符串格式化为 YYYY-MM-DD"""
    if not date_str:
        return "未知"
    try:
        # 解析包含时区信息的 ISO 8601 字符串
        dt_object = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt_object.strftime('%Y-%m-%d')
    except ValueError:
        # 如果解析失败，尝试只解析日期部分
        try:
            return datetime.strptime(date_str.split('T')[0], '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError:
            logger.warning(f"无法解析日期字符串: {date_str}")
            return "未知格式"


@tool()
class ImageSearch(BaseTool[ImageSearchParams]):
    """
    根据关键词搜索互联网上的图片，并返回包含缩略图、原图链接、来源和元数据的结果列表。
    """

    def __init__(self, **data):
        super().__init__(**data)
        # 从统一配置中获取API密钥和基础端点
        self.api_key = config.get("bing.search_api_key") # 使用统一的 Key 配置
        self.endpoint = config.get("bing.search_endpoint") # 使用统一的 Endpoint 配置

    async def execute(
        self,
        tool_context: ToolContext,
        params: ImageSearchParams
    ) -> ToolResult:
        """执行图片搜索并返回结果"""
        return await self.execute_purely(params)

    async def execute_purely(
        self,
        params: ImageSearchParams
    ) -> ToolResult:
        """执行图片搜索的核心逻辑"""
        # 使用 self.api_key 和 self.endpoint
        subscription_key = self.api_key
        endpoint = self.endpoint

        if not subscription_key:
            logger.error("图片搜索工具配置错误: 配置项 'bing.search_api_key' 未设置或为空")
            return ToolResult(error="图片搜索工具配置错误")
        if not endpoint:
            logger.error("图片搜索工具配置错误: 配置项 'bing.search_endpoint' 未设置或为空")
            return ToolResult(error="图片搜索工具配置错误")

        # 移除末尾斜杠，确保基础 URL 格式正确
        base_endpoint = endpoint.rstrip('/')
        image_search_url = f"{base_endpoint}/images/search"

        headers = {"Ocp-Apim-Subscription-Key": subscription_key}
        api_params = {"q": params.query, "count": params.count}

        logger.info(f"开始图片搜索: query='{params.query}', count={params.count}, endpoint='{image_search_url}'")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_search_url, headers=headers, params=api_params) as response:
                    response.raise_for_status()  # 对 >=400 的状态码抛出异常
                    search_results = await response.json()

            logger.info(f"图片搜索成功: query='{params.query}'")

            estimated_matches = search_results.get("totalEstimatedMatches", 0)
            image_values = search_results.get("value", [])

            markdown_parts = [
                f"## 图片搜索结果: {params.query}\n",
                f"**估计匹配数:** {estimated_matches}\n",
                "---",
            ]

            if not image_values:
                 markdown_parts.append("\n未找到相关图片。")
            else:
                for i, image_data in enumerate(image_values):
                    name = image_data.get("name", "无标题")
                    thumbnail_url = image_data.get("thumbnailUrl")
                    host_page_url = image_data.get("hostPageUrl")
                    content_url = image_data.get("contentUrl")
                    width = image_data.get("width", "N/A")
                    height = image_data.get("height", "N/A")
                    content_size_bytes = int(image_data.get("contentSize", "0 B").split(' ')[0]) # API 返回的是 '12345 B' 格式
                    encoding_format = image_data.get("encodingFormat", "未知")
                    date_published = image_data.get("datePublished") # 可能为 None

                    formatted_size = _format_bytes(content_size_bytes) if isinstance(content_size_bytes, int) and content_size_bytes > 0 else "未知"
                    formatted_date = _format_iso_date(date_published)

                    item_md = [
                        f"\n{i+1}. **{name}**"
                    ]
                    if thumbnail_url and host_page_url:
                        item_md.append(f"[![{name}]({thumbnail_url})]({host_page_url})")
                    elif thumbnail_url:
                         item_md.append(f"![{name}]({thumbnail_url})") # 降级处理，仅显示图片

                    if host_page_url:
                       item_md.append(f"*   **来源页面:** [{host_page_url}]({host_page_url})")
                    if content_url:
                        item_md.append(f"*   **原图链接:** [点击查看]({content_url})")

                    item_md.append(f"*   **尺寸:** {width}x{height}")
                    item_md.append(f"*   **体积:** {formatted_size}")
                    item_md.append(f"*   **格式:** {encoding_format}")
                    item_md.append(f"*   **发布日期:** {formatted_date}")
                    item_md.append("\n---") # 分隔符

                    markdown_parts.extend(item_md)

            final_markdown = "\n".join(markdown_parts)

            return ToolResult(
                content=final_markdown,
                extra_info={
                    "query": params.query,
                    "estimated_matches": estimated_matches,
                    "result_count": len(image_values)
                }
            )

        except aiohttp.ClientResponseError as e:
            # 保留详细日志供开发者调试
            error_details = f"API 请求失败 (状态码 {e.status}): {e.message}"
            try:
                error_content = await response.text() # 获取原始文本
                error_json = await response.json(content_type=None) # 尝试解析 JSON
                if error_json and 'errors' in error_json and error_json['errors']:
                     error_details += f". 错误信息: {error_json['errors'][0].get('message', '无详细信息')}"
                elif error_json:
                     error_details += f". 响应内容: {error_json}"
                else:
                     error_details += f". 响应内容: {error_content}"
            except Exception as json_e:
                logger.warning(f"解析 Bing API 错误响应失败: {json_e}")
                error_details += ". 无法解析详细错误响应。"
            logger.error(f"图片搜索 API 请求失败: status={e.status}, message='{e.message}', details={error_details}, query='{params.query}'")
            # 返回给 AI 的是简化后的错误信息
            return ToolResult(error=f"图片搜索 API 请求失败 (状态码 {e.status})")
        except aiohttp.ClientError as e:
            logger.error(f"图片搜索连接错误: {e}, query='{params.query}'")
            # 返回给 AI 的是简化后的错误信息
            return ToolResult(error="图片搜索时发生网络连接错误")
        except Exception as e:
            logger.exception(f"图片搜索发生未知错误: {e!s}, query='{params.query}'")
            # 返回给 AI 的是简化后的错误信息
            return ToolResult(error="图片搜索时发生内部错误")

    async def get_tool_detail(self, tool_context: ToolContext, result: ToolResult, arguments: Dict[str, Any] = None) -> Optional[ToolDetail]:
        """生成工具详情，用于前端展示"""
        if not result.content or result.error:
            return None

        query = arguments.get("query", "未知") if arguments else result.extra_info.get("query", "未知")

        try:
            # 清理查询词，使其适用于文件名
            safe_query = re.sub(r'[\\/*?:"<>|]', '_', query) # 替换非法文件名字符
            file_name = f"图片搜索结果_{safe_query[:30]}.md" # 限制文件名长度

            return ToolDetail(
                type=DisplayType.MD,
                data=FileContent(
                    file_name=file_name,
                    content=result.content # 直接使用已生成的 Markdown
                )
            )
        except Exception as e:
            logger.error(f"生成图片搜索工具详情失败: {e!s}")
            return None # 异常情况下不显示详情

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """获取工具调用后的友好动作和备注"""
        query = arguments.get("query", "") if arguments else result.extra_info.get("query", "")
        if result.error:
            remark = f"搜索图片 '{query}' 时出错"
        elif result.extra_info:
             result_count = result.extra_info.get("result_count", 0)
             remark = f"已完成图片搜索 '{query}'，找到 {result_count} 张相关图片"
        else:
             remark = f"已完成图片搜索 '{query}'" # 降级处理

        return {
            "action": "图片搜索",
            "remark": remark
        }

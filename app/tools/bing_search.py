import asyncio
import json
import os
import re
import aiohttp
from typing import Any, Dict, List, Optional

from pydantic import Field

from agentlang.config.config import config
from agentlang.context.tool_context import ToolContext
from app.core.entity.factory.tool_detail_factory import ToolDetailFactory
from app.core.entity.message.server_message import ToolDetail
from agentlang.tools.tool_result import ToolResult
from app.core.entity.tool.tool_result import BingSearchToolResult
from agentlang.logger import get_logger
from app.tools.core import BaseTool, BaseToolParams, tool

logger = get_logger(__name__)

# 搜索结果最大数量
MAX_RESULTS = 10


class BingSearchParams(BaseToolParams):
    """必应搜索参数"""
    query: List[str] = Field(
        ...,
        description="搜索查询内容数组，可同时传入多个不同的查询词并行搜索，单个查询时传入只包含一个元素的数组即可"
    )
    num_results: int = Field(
        10,
        description="每个查询返回的结果数量 (默认: 10，最大: 20)"
    )
    language: str = Field(
        "zh-CN",
        description="搜索语言 (默认: zh-CN)"
    )
    region: str = Field(
        "CN",
        description="搜索区域 (默认: CN)"
    )
    safe_search: bool = Field(
        True,
        description="是否启用安全搜索 (默认: true)"
    )
    time_period: Optional[str] = Field(
        None,
        description="搜索时间范围 (可选): day, week, month, year"
    )


# 自定义 BingSearchAPI 实现，替代 langchain_community 的 BingSearchAPIWrapper
class BingSearchAPI:
    """自定义的 Bing 搜索 API 包装器"""

    # 类变量，用于存储API是否可用的状态
    _api_unavailable = False
    _api_unavailable_reason = ""

    def __init__(self, k: int = 10, search_kwargs: dict = None):
        """
        初始化 Bing 搜索 API 包装器

        Args:
            k: 返回结果数量
            search_kwargs: 搜索参数
        """
        self.k = k
        self.search_kwargs = search_kwargs or {}
        # 从配置管理器获取 API 密钥和搜索 URL，而不是从环境变量
        self.subscription_key = config.get("bing.search_api_key", "")
        self.search_url = config.get("bing.search_endpoint", "https://api.bing.microsoft.com/v7.0") + "/search"

    async def run(self, query: str) -> str:
        """
        执行搜索并返回结果的文本摘要

        Args:
            query: 搜索查询

        Returns:
            str: 搜索结果的文本摘要
        """
        search_results = await self._search(query)
        if not search_results:
            return "No results found"

        # 格式化为文本
        result_str = ""
        for i, result in enumerate(search_results, 1):
            result_str += f"{i}. {result['title']}: {result['snippet']}\n"

        return result_str

    async def results(self, query: str, k: int = None) -> List[Dict[str, Any]]:
        """
        执行搜索并返回结构化结果

        Args:
            query: 搜索查询
            k: 结果数量，覆盖初始化时设置的值

        Returns:
            List[Dict[str, Any]]: 搜索结果列表
        """
        limit = k if k is not None else self.k
        search_results = await self._search(query, limit)
        return search_results

    async def _search(self, query: str, limit: int = None) -> List[Dict[str, Any]]:
        """
        执行实际的 Bing 搜索 API 调用

        Args:
            query: 搜索查询
            limit: 结果数量限制

        Returns:
            List[Dict[str, Any]]: 搜索结果列表
        """
        # 检查API是否已被标记为不可用
        if BingSearchAPI._api_unavailable:
            logger.error(f"Bing Search API 不可用: {BingSearchAPI._api_unavailable_reason}")
            return []

        if not self.subscription_key:
            raise ValueError("Bing Search API key is required")

        # 设置请求头
        headers = {
            "Ocp-Apim-Subscription-Key": self.subscription_key,
            "Accept": "application/json"
        }

        # 设置查询参数
        params = {
            "q": query,
            "count": limit or self.k,
            **self.search_kwargs
        }

        # 清理参数
        for k, v in list(params.items()):
            if v is None:
                del params[k]

        try:
            # 发送 HTTP 请求
            async with aiohttp.ClientSession() as session:
                async with session.get(self.search_url, headers=headers, params=params) as response:
                    if response.status != 200:
                        error_detail = await response.text()
                        # 特殊处理401错误（无效的API密钥或端点）
                        if response.status == 401:
                            BingSearchAPI._api_unavailable = True
                            BingSearchAPI._api_unavailable_reason = f"API密钥无效或API端点错误: {error_detail}"
                            logger.error(f"Bing Search API 请求失败: {response.status} {error_detail}")
                            logger.error("由于401错误（无效的API密钥或端点），Bing Search API 已被标记为不可用")
                        else:
                            logger.error(f"Bing Search API 请求失败: {response.status} {error_detail}")
                        return []

                    data = await response.json()

                    # 解析响应数据
                    if "webPages" not in data or "value" not in data["webPages"]:
                        return []

                    results = []
                    for item in data["webPages"]["value"]:
                        results.append({
                            "title": item.get("name", ""),
                            "link": item.get("url", ""),
                            "snippet": item.get("snippet", "")
                        })

                    return results[:limit or self.k]
        except Exception as e:
            logger.error(f"Bing Search API 请求异常: {e}")
            return []


@tool()
class BingSearch(BaseTool[BingSearchParams]):
    """
    必应搜索工具，用于进行网络搜索。
    支持多个查询并行处理，善用并发搜索，可大幅提高搜索效率。
    根据信息收集规则，搜索结果中的摘要不是有效来源，必须通过浏览器访问原始页面获取完整信息。
    搜索结果将包含标题、URL、摘要和来源网站。

    使用场景：
    - 查找最新信息和新闻
    - 搜索特定主题的资料和参考
    - 查询事实和数据
    - 寻找解决方案和教程
    - 同时搜索多个相关主题，高效并发获取多种信息

    注意：
    - 搜索结果仅提供线索，需要通过浏览器工具访问原始页面获取完整信息
    - 应从多个搜索结果中获取信息以进行交叉验证
    - 对于复杂查询，应分解为多个简单查询并利用工具的并发能力
    """

    def __init__(self, **data):
        super().__init__(**data)
        # 从配置中获取API密钥和端点
        self.api_key = config.get("bing.search_api_key", default="")
        self.endpoint = config.get("bing.search_endpoint", default="https://api.bing.microsoft.com/v7.0")

    async def execute(
        self,
        tool_context: ToolContext,
        params: BingSearchParams
    ) -> ToolResult:
        """
        执行必应搜索并返回格式化的结果。

        Args:
            tool_context: 工具上下文
            params: 搜索参数对象

        Returns:
            BingSearchToolResult: 包含搜索结果的工具结果
        """
        # 首先检查API是否已被标记为不可用
        if BingSearchAPI._api_unavailable:
            logger.error(f"Bing Search API 不可用: {BingSearchAPI._api_unavailable_reason}")
            return BingSearchToolResult(error=f"搜索服务不可用: {BingSearchAPI._api_unavailable_reason}")

        try:
            # 获取参数
            query = params.query
            num_results = params.num_results
            language = params.language
            region = params.region
            safe_search = params.safe_search
            time_period = params.time_period

            # 验证参数
            if not query:
                return BingSearchToolResult(content="搜索查询不能为空")

            if num_results > MAX_RESULTS:
                num_results = MAX_RESULTS

            # 记录搜索请求
            logger.info(f"执行互联网搜索: 查询数量={len(query)}, 每个查询结果数量={num_results}")

            # 并发执行所有查询
            tasks = [
                self._perform_search(
                    query=q,
                    num_results=num_results,
                    language=language,
                    region=region,
                    safe_search=safe_search,
                    time_period=time_period,
                )
                for q in query
            ]
            all_results = await asyncio.gather(*tasks)

            # 创建结构化结果
            result = self._handle_queries_results(query, all_results)

            if len(query) > 1:
                message = f"我已从搜索引擎中分别搜索了: {', '.join(query)}"
            else:
                message = f"我已从搜索引擎中搜索了: {query[0]}"
            # 设置输出文本
            output_dict = {
                "message": message,
                "results": result.output_results_to_dict()
            }
            result.content = json.dumps(output_dict, ensure_ascii=False)

            return result

        except Exception as e:
            logger.exception(f"必应搜索操作失败: {e!s}")
            return BingSearchToolResult(error=f"搜索操作失败: {e!s}")

    def _handle_queries_results(self, queries: List[str], all_results: List[List[Dict[str, Any]]]) -> BingSearchToolResult:
        """
        格式化多个查询的搜索结果

        Args:
            queries: 查询字符串列表
            all_results: 每个查询对应的搜索结果列表

        Returns:
            BingSearchToolResult: 包含所有格式化搜索结果的工具结果
        """
        result = BingSearchToolResult(content="")

        # 格式化所有结果
        for q, search_results in zip(queries, all_results):
            result.set_output_results(q, search_results)
            result.set_search_results(q, search_results)

        return result

    async def _perform_search(
        self, query: str, num_results: int, language: str, region: str, safe_search: bool, time_period: Optional[str]
    ) -> List[Dict[str, Any]]:
        """执行实际的搜索请求，使用自定义的BingSearchAPI类"""
        # 设置搜索参数
        search_params = {
            "count": num_results,
            "setLang": language,
            "mkt": f"{language}-{region}",
        }

        # 设置安全搜索
        if safe_search:
            search_params["safeSearch"] = "Strict"
        else:
            search_params["safeSearch"] = "Off"

        # 设置时间范围
        if time_period:
            if time_period == "day":
                search_params["freshness"] = "Day"
            elif time_period == "week":
                search_params["freshness"] = "Week"
            elif time_period == "month":
                search_params["freshness"] = "Month"

        try:
            # 不再设置环境变量，而是直接使用配置
            # 创建 BingSearchAPI 实例时，它会从配置获取 API 密钥和搜索 URL
            search = BingSearchAPI(
                k=num_results,  # 返回结果数量
                search_kwargs={
                    "mkt": f"{language}-{region}",  # 设置区域
                    "setLang": language,  # 设置语言
                },
            )

            # 执行搜索请求
            # 获取结构化结果
            search_results = await search.results(query, num_results)

            # 增强结果，添加来源网站和favicon
            for item in search_results:
                # 提取域名（来源网站）
                domain = self._extract_domain(item["link"])
                item["domain"] = domain
                item["icon_url"] = self._get_favicon_url(domain)

            return search_results

        except Exception as e:
            logger.error(f"必应搜索API请求失败: {e!s}")
            return []  # 返回空结果

    def _extract_domain(self, url: str) -> str:
        """从URL中提取域名"""
        try:
            domain = re.search(r"https?://([^/]+)", url)
            if domain:
                return domain.group(1)
            return url
        except Exception:
            return url

    def _get_favicon_url(self, domain: str) -> str:
        """生成网站favicon的URL"""
        return f"https://{domain}/favicon.ico"

    async def get_tool_detail(self, tool_context: ToolContext, result: ToolResult, arguments: Dict[str, Any] = None) -> Optional[ToolDetail]:
        """
        生成工具详情，用于前端展示

        Args:
            tool_context: 工具上下文
            result: 工具结果
            arguments: 工具参数

        Returns:
            Optional[ToolDetail]: 工具详情
        """
        if not result.content:
            return None

        try:
            if not isinstance(result, BingSearchToolResult):
                return None

            # 使用工厂创建展示详情
            return ToolDetailFactory.create_search_detail_from_search_results(
                search_results=result.search_results,
            )
        except Exception as e:
            logger.error(f"生成工具详情失败: {e!s}")
            return None

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """获取工具调用后的友好动作和备注"""
        if not arguments or "query" not in arguments:
            return {
                "action": "互联网搜索",
                "remark": "已完成搜索"
            }

        query = arguments["query"]
        if len(query) > 1:
            return {
                "action": "互联网搜索",
                "remark": f"搜索: {', '.join(query)}"
            }
        return {
            "action": "互联网搜索",
            "remark": f"搜索: {query[0]}"
        }

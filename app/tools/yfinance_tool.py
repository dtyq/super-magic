"""YFinance 工具模块

提供从 Yahoo Finance 获取金融市场数据的功能
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Optional

import yfinance as yf
from pydantic import Field, field_validator

from agentlang.context.tool_context import ToolContext
from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from app.core.entity.tool.tool_result import YFinanceToolResult
from app.tools.core import BaseTool, BaseToolParams, tool

logger = get_logger(__name__)

# 可用的查询类型
QUERY_TYPES = ["history", "info", "financials", "actions", "dividends", "institutional_holders",
              "major_holders", "balance_sheet", "cashflow", "earnings", "sustainability",
              "recommendations", "calendar", "news", "market_status"]

# 时间周期映射
PERIOD_MAPPING = {
    "1d": "1 天",
    "5d": "5 天",
    "1mo": "1 个月",
    "3mo": "3 个月",
    "6mo": "6 个月",
    "1y": "1 年",
    "2y": "2 年",
    "5y": "5 年",
    "10y": "10 年",
    "ytd": "今年至今",
    "max": "最大范围"
}

# 有效的时间间隔
VALID_INTERVALS = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]


class YFinanceParams(BaseToolParams):
    """YFinance 工具参数"""

    ticker: str = Field(
        ...,
        description="股票代码或股票代码列表，如 AAPL (苹果)、MSFT (微软)、GOOG (谷歌)、BABA (阿里巴巴)、9988.HK (港股阿里巴巴)、600519.SS (贵州茅台)等"
    )

    query_type: str = Field(
        ...,
        description=f"查询类型，支持以下选项：{', '.join(QUERY_TYPES)}"
    )

    period: str = Field(
        "1mo",
        description="时间范围，仅适用于 history 查询。可选值: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max"
    )

    interval: str = Field(
        "1d",
        description="价格数据的时间间隔，仅适用于 history 查询。可选值: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo"
    )

    limit: int = Field(
        10,
        description="返回结果的最大条目数，用于限制返回数据量"
    )

    @field_validator("query_type")
    def validate_query_type(cls, v):
        """验证查询类型是否有效"""
        if v not in QUERY_TYPES:
            raise ValueError(f"无效的查询类型: {v}。有效选项: {', '.join(QUERY_TYPES)}")
        return v

    @field_validator("period")
    def validate_period(cls, v):
        """验证时间范围是否有效"""
        if v not in PERIOD_MAPPING:
            raise ValueError(f"无效的时间范围: {v}。有效选项: {', '.join(PERIOD_MAPPING.keys())}")
        return v

    @field_validator("interval")
    def validate_interval(cls, v):
        """验证时间间隔是否有效"""
        if v not in VALID_INTERVALS:
            raise ValueError(f"无效的时间间隔: {v}。有效选项: {', '.join(VALID_INTERVALS)}")
        return v

    @classmethod
    def get_custom_error_message(cls, field_name: str, error_type: str) -> Optional[str]:
        """获取自定义参数错误信息"""
        if field_name == "ticker" and error_type == "missing":
            return "请提供股票代码，例如 AAPL (苹果)、MSFT (微软)或 600519.SS (贵州茅台)"

        if field_name == "query_type" and error_type == "missing":
            return f"请提供查询类型，有效选项: {', '.join(QUERY_TYPES)}"

        return None


@tool()
class YFinance(BaseTool[YFinanceParams]):
    """Yahoo Finance 金融数据工具"""

    # 设置参数类
    params_class = YFinanceParams

    # 设置工具元数据
    name = "yfinance"
    description = """Yahoo Finance 金融数据工具，用于获取股票和金融市场数据。
支持获取股票价格历史、公司基本信息、财务数据、股息信息等各类金融数据。
数据来源为 Yahoo Finance，通过 yfinance 库获取。

使用场景:
- 获取股票历史价格和趋势分析
- 获取公司基本信息和财务健康状况
- 获取股息数据和分红历史
- 获取财务报表数据(资产负债表、现金流量表等)
- 获取机构持股和主要持股人信息
- 获取市场状态和热门股票信息

支持的查询类型:
- history: 历史价格数据
- info: 公司基本信息和概览
- financials: 财务报表摘要
- actions: 股票行动(分红、拆分等)
- dividends: 股息分红历史
- institutional_holders: 机构持股情况
- major_holders: 主要持股人
- balance_sheet: 资产负债表
- cashflow: 现金流量表
- earnings: 收益数据
- sustainability: 可持续发展评级
- recommendations: 分析师推荐
- calendar: 财报日历
- news: 相关新闻
- market_status: 市场状态

注意事项:
- 请提供准确的股票代码，美股代码直接使用(如AAPL)，港股需添加.HK后缀(如9988.HK)，A股需添加.SS或.SZ后缀(如600519.SS)
- 历史数据查询支持不同的时间范围和间隔设置
- 部分查询类型可能对某些股票不可用
- 数据可能有延迟，不适合实时交易决策
"""

    async def execute(
        self,
        tool_context: ToolContext,
        params: YFinanceParams
    ) -> ToolResult:
        """
        执行 YFinance 查询并返回格式化的结果。

        Args:
            tool_context: 工具上下文
            params: 查询参数对象

        Returns:
            YFinanceToolResult: 包含查询结果的工具结果
        """
        try:
            # 获取参数
            ticker = params.ticker
            query_type = params.query_type
            period = params.period
            interval = params.interval
            limit = params.limit

            # 记录查询请求
            logger.info(f"执行 YFinance 查询: 股票={ticker}, 类型={query_type}, 周期={period}, 间隔={interval}")

            # 创建结果对象
            result = YFinanceToolResult(content="")
            result.set_ticker(ticker)
            result.set_query_type(query_type)

            if query_type == "history":
                result.set_time_period(period)

            # 执行查询
            data = await self._perform_query(ticker, query_type, period, interval, limit)

            # 处理查询结果
            if not data:
                return YFinanceToolResult(
                    error=f"没有找到 {ticker} 的 {query_type} 数据",
                    ticker=ticker,
                    query_type=query_type
                )

            # 格式化输出
            formatted_result = self._format_result(ticker, query_type, data, period)
            result.content = formatted_result

            return result

        except Exception as e:
            logger.exception(f"YFinance 查询操作失败: {e!s}")
            return YFinanceToolResult(error=f"金融数据查询失败: {e!s}")

    async def _perform_query(
        self,
        ticker: str,
        query_type: str,
        period: str,
        interval: str,
        limit: int
    ) -> Any:
        """执行实际的 YFinance 查询

        Args:
            ticker: 股票代码
            query_type: 查询类型
            period: 时间范围
            interval: 时间间隔
            limit: 限制结果数量

        Returns:
            Any: 查询结果数据
        """
        # 创建异步任务
        loop = asyncio.get_event_loop()

        try:
            # 使用 run_in_executor 将同步 YFinance 操作转换为异步
            result = await loop.run_in_executor(
                None,
                lambda: self._sync_query(ticker, query_type, period, interval, limit)
            )
            return result
        except Exception as e:
            logger.error(f"YFinance 查询失败: {e!s}")
            return None

    def _sync_query(
        self,
        ticker: str,
        query_type: str,
        period: str,
        interval: str,
        limit: int
    ) -> Any:
        """同步执行 YFinance 查询

        Args:
            ticker: 股票代码
            query_type: 查询类型
            period: 时间范围
            interval: 时间间隔
            limit: 限制结果数量

        Returns:
            Any: 查询结果数据
        """
        # 获取股票信息
        ticker_obj = yf.Ticker(ticker)

        # 根据查询类型执行不同操作
        if query_type == "history":
            # 获取历史价格数据
            df = ticker_obj.history(period=period, interval=interval)
            # 转换为字典列表并限制数量
            records = df.tail(limit).reset_index().to_dict('records')
            # 处理日期格式
            for record in records:
                if 'Date' in record and isinstance(record['Date'], datetime):
                    record['Date'] = record['Date'].strftime('%Y-%m-%d %H:%M:%S')
            return records

        elif query_type == "info":
            # 获取公司基本信息
            return ticker_obj.info

        elif query_type == "financials":
            # 获取财务报表摘要
            financials = ticker_obj.financials
            if financials is not None and not financials.empty:
                return financials.to_dict()
            return None

        elif query_type == "actions":
            # 获取股票行动(分红、拆分等)
            actions = ticker_obj.actions
            if actions is not None and not actions.empty:
                records = actions.tail(limit).reset_index().to_dict('records')
                for record in records:
                    if 'Date' in record and isinstance(record['Date'], datetime):
                        record['Date'] = record['Date'].strftime('%Y-%m-%d')
                return records
            return None

        elif query_type == "dividends":
            # 获取股息分红历史
            dividends = ticker_obj.dividends
            if dividends is not None and not dividends.empty:
                records = dividends.tail(limit).reset_index().to_dict('records')
                for record in records:
                    if 'Date' in record and isinstance(record['Date'], datetime):
                        record['Date'] = record['Date'].strftime('%Y-%m-%d')
                return records
            return None

        elif query_type == "institutional_holders":
            # 获取机构持股情况
            holders = ticker_obj.institutional_holders
            if holders is not None and not holders.empty:
                return holders.head(limit).to_dict('records')
            return None

        elif query_type == "major_holders":
            # 获取主要持股人
            holders = ticker_obj.major_holders
            if holders is not None and not holders.empty:
                return holders.to_dict('records')
            return None

        elif query_type == "balance_sheet":
            # 获取资产负债表
            balance_sheet = ticker_obj.balance_sheet
            if balance_sheet is not None and not balance_sheet.empty:
                return balance_sheet.to_dict()
            return None

        elif query_type == "cashflow":
            # 获取现金流量表
            cashflow = ticker_obj.cashflow
            if cashflow is not None and not cashflow.empty:
                return cashflow.to_dict()
            return None

        elif query_type == "earnings":
            # 获取收益数据
            earnings = ticker_obj.earnings
            if earnings is not None and not earnings.empty:
                return earnings.to_dict()
            return None

        elif query_type == "sustainability":
            # 获取可持续发展评级
            sustainability = ticker_obj.sustainability
            if sustainability is not None and not sustainability.empty:
                return sustainability.to_dict()
            return None

        elif query_type == "recommendations":
            # 获取分析师推荐
            recommendations = ticker_obj.recommendations
            if recommendations is not None and not recommendations.empty:
                records = recommendations.tail(limit).reset_index().to_dict('records')
                for record in records:
                    if 'Date' in record and isinstance(record['Date'], datetime):
                        record['Date'] = record['Date'].strftime('%Y-%m-%d')
                return records
            return None

        elif query_type == "calendar":
            # 获取财报日历
            calendar = ticker_obj.calendar
            if calendar is not None and not calendar.empty:
                return calendar.to_dict()
            return None

        elif query_type == "news":
            # 获取相关新闻
            news = ticker_obj.news
            return news[:limit] if news else None

        elif query_type == "market_status":
            # 获取市场状态
            # 由于 yfinance 没有直接的市场状态 API，我们可以通过获取主要指数的最新数据来展示市场状态
            indices = ['^DJI', '^GSPC', '^IXIC', '^HSI', '000001.SS']  # 道琼斯、标普500、纳斯达克、恒生指数、上证指数
            market_data = {}

            for index in indices:
                try:
                    index_ticker = yf.Ticker(index)
                    last_quote = index_ticker.history(period='1d')
                    if not last_quote.empty:
                        last_row = last_quote.iloc[-1]
                        change = last_row['Close'] - last_row['Open']
                        change_percent = (change / last_row['Open']) * 100

                        market_data[index] = {
                            'name': self._get_index_name(index),
                            'price': round(last_row['Close'], 2),
                            'change': round(change, 2),
                            'change_percent': round(change_percent, 2),
                            'volume': last_row['Volume']
                        }
                except Exception as e:
                    logger.error(f"获取指数 {index} 数据失败: {e!s}")

            return market_data

        # 默认返回 None
        return None

    def _format_result(self, ticker: str, query_type: str, data: Any, period: str = None) -> str:
        """格式化查询结果为友好的文本输出

        Args:
            ticker: 股票代码
            query_type: 查询类型
            data: 查询结果数据
            period: 时间范围

        Returns:
            str: 格式化后的结果文本
        """
        if not data:
            return f"没有找到 {ticker} 的 {query_type} 数据"

        # 根据查询类型进行不同的格式化
        if query_type == "history":
            # 格式化历史价格数据
            period_text = PERIOD_MAPPING.get(period, period)
            result = {
                "message": f"{ticker} 在过去 {period_text} 的历史价格数据",
                "data": data
            }
            return json.dumps(result, ensure_ascii=False)

        elif query_type == "info":
            # 格式化公司基本信息
            # 选择最重要的字段显示
            important_fields = [
                'shortName', 'longName', 'sector', 'industry', 'website',
                'market', 'marketCap', 'currency', 'exchange',
                'previousClose', 'open', 'dayLow', 'dayHigh', 'regularMarketPrice',
                'fiftyTwoWeekLow', 'fiftyTwoWeekHigh', 'volume', 'averageVolume',
                'trailingPE', 'forwardPE', 'dividendRate', 'dividendYield',
                'beta', 'bookValue', 'priceToBook', 'earningsGrowth',
                'revenueGrowth', 'totalRevenue', 'grossMargins', 'profitMargins'
            ]

            # 过滤数据，只保留重要字段
            filtered_data = {k: v for k, v in data.items() if k in important_fields and v is not None}

            result = {
                "message": f"{ticker} 的公司基本信息",
                "data": filtered_data
            }
            return json.dumps(result, ensure_ascii=False)

        elif query_type in ["financials", "balance_sheet", "cashflow", "earnings", "sustainability", "calendar"]:
            # 这些是DataFrame转换的嵌套字典，需要特殊处理
            result = {
                "message": f"{ticker} 的 {query_type} 数据",
                "data": self._process_dataframe_dict(data)
            }
            return json.dumps(result, ensure_ascii=False)

        elif query_type == "news":
            # 格式化新闻数据
            formatted_news = []
            for news_item in data:
                formatted_news.append({
                    "title": news_item.get("title", ""),
                    "publisher": news_item.get("publisher", ""),
                    "link": news_item.get("link", ""),
                    "publish_time": news_item.get("providerPublishTime", ""),
                    "type": news_item.get("type", ""),
                    "relatedTickers": news_item.get("relatedTickers", [])
                })

            result = {
                "message": f"{ticker} 的相关新闻",
                "data": formatted_news
            }
            return json.dumps(result, ensure_ascii=False)

        elif query_type == "market_status":
            # 格式化市场状态
            result = {
                "message": "当前主要市场指数状态",
                "data": data
            }
            return json.dumps(result, ensure_ascii=False)

        else:
            # 其他类型直接返回JSON字符串
            result = {
                "message": f"{ticker} 的 {query_type} 数据",
                "data": data
            }
            return json.dumps(result, ensure_ascii=False)

    def _process_dataframe_dict(self, data: Dict) -> Dict:
        """处理从DataFrame转换来的嵌套字典，使其适合JSON序列化

        Args:
            data: DataFrame转换的字典

        Returns:
            Dict: 处理后的字典
        """
        result = {}

        for column, values in data.items():
            column_data = {}

            for date, value in values.items():
                # 将日期对象转换为字符串
                if isinstance(date, datetime):
                    date_str = date.strftime('%Y-%m-%d')
                else:
                    date_str = str(date)

                # 确保值是可序列化的
                if isinstance(value, (int, float, str, bool)) or value is None:
                    column_data[date_str] = value
                elif hasattr(value, 'item'):  # numpy类型
                    column_data[date_str] = value.item()
                else:
                    column_data[date_str] = str(value)

            result[str(column)] = column_data

        return result

    def _get_index_name(self, index_symbol: str) -> str:
        """获取指数的中文名称

        Args:
            index_symbol: 指数代码

        Returns:
            str: 指数名称
        """
        index_names = {
            '^DJI': '道琼斯工业平均指数',
            '^GSPC': '标普500指数',
            '^IXIC': '纳斯达克综合指数',
            '^HSI': '恒生指数',
            '000001.SS': '上证指数'
        }

        return index_names.get(index_symbol, index_symbol)

"""
HTTP订阅流实现

提供基于HTTP的流实现，用于将消息发送到订阅的HTTP端点
"""

import asyncio
import json
from typing import Dict, Optional, Tuple

import aiohttp

from agentlang.event.event import EventType
from agentlang.logger import get_logger
from app.core.entity.message.client_message import MessageSubscriptionConfig
from app.core.stream import Stream

logger = get_logger(__name__)

class HTTPSubscriptionStream(Stream):
    """A Stream implementation for sending data to HTTP subscription endpoints.
    
    This class provides a way to send messages to an HTTP endpoint specified in the
    message_subscription_config.
    """

    def __init__(self, config: MessageSubscriptionConfig):
        """Initialize the HTTP subscription stream.
        
        Args:
            config: The subscription configuration containing method, endpoint, and headers.
        """
        super().__init__()
        self._config = config
        self._session = None
        self._max_retries = 3
        self._base_retry_delay = 1.0  # 基础延迟(秒)
        self._max_retry_delay = 10.0  # 最大延迟(秒)

        self.ignore_events([EventType.AFTER_CLIENT_CHAT])
        logger.info("已配置HTTPSubscriptionStream忽略AFTER_CLIENT_CHAT事件")

    async def _ensure_session(self):
        """Ensure an HTTP session exists."""
        if self._session is None:
            # 创建带有追踪功能的会话
            trace_config = aiohttp.TraceConfig()

            async def on_request_start(session, trace_config_ctx, params):
                logger.debug(f"开始请求: {params.url}")

            async def on_request_end(session, trace_config_ctx, params):
                logger.debug(f"完成请求, 状态: {params.response.status}")

            trace_config.on_request_start.append(on_request_start)
            trace_config.on_request_end.append(on_request_end)

            self._session = aiohttp.ClientSession(trace_configs=[trace_config])

    async def read(self, size: Optional[int] = None) -> str:
        """Read is not supported for HTTPSubscriptionStream.
        
        Args:
            size: Ignored.
            
        Raises:
            NotImplementedError: Always raised as read is not supported.
        """
        raise NotImplementedError("HTTPSubscriptionStream does not support read operations")

    async def _should_retry(self, response) -> bool:
        """
        基于响应状态码和响应体内容判断是否需要重试
        
        Args:
            response: HTTP响应对象
            
        Returns:
            bool: 是否应该重试请求
        """
        retry_decision = False  # 默认不重试

        # 记录请求信息
        logger.debug(f"检查是否需要重试: URL={response.url}, 状态码={response.status}")

        if response.status != 200:
            retry_decision = True
            logger.warning(f"服务器错误状态码: {response.status}，将进行重试: {retry_decision}")
            return retry_decision

        # 检查响应体内容
        try:
            content = await response.text()

            try:
                response_json = json.loads(content)

                if 'code' in response_json:
                    code = response_json.get('code')
                    if code != 1000:
                        retry_decision = True
                        logger.warning(f"响应code不等于1000 (code={code})，将进行重试: {retry_decision}")
                else:
                    retry_decision = True
                    logger.warning(f"响应中没有code字段，将进行重试: {retry_decision}")

            except json.JSONDecodeError:
                retry_decision = True
                logger.warning(f"响应不是有效的JSON格式，将进行重试: {retry_decision}")
        except Exception as e:
            retry_decision = True
            logger.warning(f"检查响应内容时出错: {e!s}，将进行重试: {retry_decision}")

        # 最终决策日志
        logger.debug(f"should_retry 最终返回: {retry_decision}")
        return retry_decision

    async def _send_request_with_retry(self, method: str, url: str, headers: Dict, data: str) -> Tuple[bool, Optional[aiohttp.ClientResponse]]:
        """
        发送HTTP请求，支持自定义重试逻辑
        
        Returns:
            元组 (success, response)
        """
        retry_count = 0
        last_exception = None
        last_response = None

        while retry_count <= self._max_retries:
            current_attempt = retry_count + 1
            try:
                # 发送请求
                logger.debug(f"正在进行第 {current_attempt} 次请求尝试...")
                async with self._session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=data
                ) as response:
                    # 记录一份响应数据的副本，用于判断是否重试
                    response_copy = response

                    # 判断是否需要重试
                    if await self._should_retry(response):
                        if retry_count < self._max_retries:
                            retry_count += 1
                            delay = min(self._base_retry_delay * (2 ** (retry_count - 1)), self._max_retry_delay)
                            logger.info(f"第 {current_attempt} 次尝试失败，将在 {delay:.2f} 秒后重试...")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            # 已达到最大重试次数
                            logger.warning(f"已达到最大重试次数 ({self._max_retries})，不再重试")
                            return True, response
                    else:
                        # 不需要重试，返回成功
                        return True, response
            except Exception as e:
                last_exception = e
                logger.error(f"请求发生异常 (尝试 {current_attempt}/{self._max_retries + 1}): {e!s}")

                if retry_count < self._max_retries:
                    retry_count += 1
                    delay = min(self._base_retry_delay * (2 ** (retry_count - 1)), self._max_retry_delay)
                    logger.info(f"将在 {delay:.2f} 秒后重试...")
                    await asyncio.sleep(delay)
                else:
                    # 已达到最大重试次数
                    logger.warning(f"已达到最大重试次数 ({self._max_retries})，不再重试")
                    return False, None

        # 如果执行到这里，表示重试后仍然失败
        return False, last_response

    async def write(self, data: str, data_type: str = "json") -> int:
        """Write string data to the HTTP subscription endpoint.
        
        Args:
            data: The string data to be sent.
            data_type: The type of data being sent, defaults to "json".
            
        Returns:
            The number of bytes written.
            
        Raises:
            IOError: When there's an error writing to the HTTP endpoint.
        """
        try:
            await self._ensure_session()

            # 准备请求头和内容
            headers = dict(self._config.headers)

            if data_type == "json":
                # 确保Content-Type是application/json
                if "Content-Type" not in headers:
                    headers["Content-Type"] = "application/json"

            # 发送请求，使用自定义重试逻辑
            success, response = await self._send_request_with_retry(
                method=self._config.method,
                url=self._config.url,
                headers=headers,
                data=data
            )

            if not success:
                raise IOError("Failed to write to HTTP endpoint after retries")

            # 检查最终响应状态
            if response.status >= 400:
                error_text = await response.text()
                logger.error(f"HTTP subscription failed with status {response.status}: {error_text}")
                raise IOError(f"Failed to write to HTTP endpoint: Status {response.status}")

            return len(data)

        except Exception as e:
            logger.error(f"Failed to write to HTTP endpoint: {e!s}")
            raise IOError(f"Failed to write to HTTP endpoint: {e!s}")

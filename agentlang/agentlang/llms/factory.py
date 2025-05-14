"""
LLM Factory module for creating different LLM clients.

This module provides a factory pattern for creating different LLM clients
based on the model ID provided.
"""

import os
import logging
import re
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from agentlang.config.config import config
from agentlang.interface.context import AgentContextInterface
from agentlang.llms.token_usage.tracker import TokenUsageTracker
from agentlang.llms.token_usage.pricing import ModelPricing
from agentlang.llms.token_usage.report import TokenUsageReport
from agentlang.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = int(config.get("llm.api_timeout", 600))
MAX_RETRIES = int(config.get("llm.api_max_retries", 3))


class LLMClientConfig(BaseModel):
    """Configuration for LLM clients."""

    model_id: str
    api_key: str
    api_base_url: Optional[str] = None
    name: str
    provider: str
    temperature: float = 0.7
    max_output_tokens: int = 4 * 1024
    max_context_tokens: int = 8 * 1024
    top_p: float = 1.0
    stop: Optional[List[str]] = None
    extra_params: Dict[str, Any] = {}
    supports_tool_use: bool = True
    type: str = "llm"

class LLMFactory:
    """Factory for creating LLM clients."""

    _clients = {}
    _configs = {}

    # 初始化 token 使用跟踪器和相关服务
    token_tracker = TokenUsageTracker()

    # 从配置中加载价格配置
    models_config = config.get("models", {})
    pricing = ModelPricing(models_config=models_config)
    sandbox_id = os.environ.get("SANDBOX_ID", "default")

    # 初始化 TokenUsageReport
    _ = TokenUsageReport.get_instance(
        sandbox_id=sandbox_id,
        token_tracker=token_tracker,
        pricing=pricing
    )

    @classmethod
    def register_config(cls, llm_config: LLMClientConfig) -> None:
        """Register a configuration for a model ID.

        Args:
            config: The configuration to register.
        """
        cls._configs[llm_config.model_id] = llm_config

    @classmethod
    def get(cls, model_id: str) -> Any:
        """Get a client for the given model ID.

        Args:
            model_id: The model ID to get a client for.

        Returns:
            The client for the given model ID.

        Raises:
            ValueError: If the model ID is not supported.
        """
        if model_id in cls._clients:
            return cls._clients[model_id]

        if model_id not in cls._configs:
            # 从配置文件中读取模型配置
            model_config = config.get("models", {}).get(model_id)
            if not model_config:
                raise ValueError(f"Unsupported model ID: {model_id}")
            # 过滤 type 不是 llm 的配置
            if model_config.get("type") != "llm":
                raise ValueError(f"Model {model_id} is not a LLM model")

            llm_config = LLMClientConfig(
                model_id=model_id,
                api_key=model_config["api_key"],
                api_base_url=model_config["api_base_url"],
                name=str(model_config["name"]),
                provider=model_config["provider"],
                supports_tool_use=model_config.get("supports_tool_use", False),
                max_output_tokens=model_config.get("max_output_tokens", 4 * 1024),
                max_context_tokens=model_config.get("max_context_tokens", 8 * 1024),
                temperature=model_config.get("temperature", 0.7),
                top_p=model_config.get("top_p", 1.0),
            )
            cls._configs[model_id] = llm_config

        llm_config = cls._configs[model_id]
        available_providers = ["openai"]
        if llm_config.provider not in available_providers:
            raise ValueError(f"Unsupported provider: {llm_config.provider}")

        if llm_config.provider == "openai":
            client = cls._create_openai_client(llm_config)
            cls._clients[model_id] = client
            return client

    @classmethod
    async def call_with_tool_support(
        cls,
        model_id: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stop: Optional[List[str]] = None,
        agent_context: Optional[AgentContextInterface] = None
    ) -> ChatCompletion:
        """使用工具支持调用 LLM。

        根据模型配置使用工具调用。
        对于支持工具调用的模型，直接使用 OpenAI API 的工具调用功能。

        Args:
            model_id: 要使用的模型 ID。
            messages: 聊天消息历史。
            tools: 可用工具的列表，可选。
            stop: 终止序列列表，可选。
            agent_context: Agent 上下文接口，可选。

        Returns:
            LLM 响应。

        Raises:
            ValueError: 如果模型 ID 不支持。
        """
        # 注意：不再在这里检查 cost limit，而是通过事件机制处理

        client = cls.get(model_id)
        if not client:
            raise ValueError(f"无法获取模型 ID 为 {model_id} 的客户端")

        # 获取模型配置
        llm_config = cls._configs.get(model_id)
        if not llm_config:
            raise ValueError(f"找不到模型 ID 为 {model_id} 的配置")

        # 使用原生工具调用
        # 构建请求参数
        request_params = {
            "model": llm_config.name,
            "messages": messages,
            "temperature": llm_config.temperature,
            #"max_output_tokens": llm_config.max_output_tokens,  # 先去掉这个传参，暂时还搞不太明白怎么算
            "top_p": llm_config.top_p,
        }

        # --- 开始: 添加 AWS AutoCache 配置 ---
        aws_autocache_config = config.get("llm.aws_autocache", {})
        aws_autocache_enabled_str = str(aws_autocache_config.get("enabled", "true")).lower()
        aws_autocache_enabled = aws_autocache_enabled_str == "true"

        if aws_autocache_enabled:
            try:
                max_cache_points = int(aws_autocache_config.get("max_cache_points", 4))
                max_cache_points = max(min(max_cache_points, 4), 1) # 约束在 [1, 4]

                min_cache_tokens = int(aws_autocache_config.get("min_cache_tokens", 2048))
                min_cache_tokens = max(min_cache_tokens, 2048) # 最小 2048

                refresh_point_min_tokens = int(aws_autocache_config.get("refresh_point_min_tokens", 5000))
                refresh_point_min_tokens = max(refresh_point_min_tokens, 2048) # 最小 2048

                autocache_params = {
                    'auto_cache': True, # 因为 enabled=True 才进入此分支
                    'auto_cache_config': {
                        'max_cache_points': max_cache_points,
                        'min_cache_tokens': min_cache_tokens,
                        'refresh_point_min_tokens': refresh_point_min_tokens,
                    }
                }
            except ValueError as e:
                logger.warning(f"解析 AWS AutoCache 配置时出错: {e}. 将不应用 AutoCache 配置。", exc_info=True)
        # --- 结束: 添加 AWS AutoCache 配置 ---

        # 添加终止序列（如果提供）
        if stop:
            request_params["stop"] = stop

        # 添加工具（如果提供且模型支持工具使用）
        if tools and llm_config.supports_tool_use:
            request_params["tools"] = tools
            # 添加 tool_choice 参数，设置为 "auto" 以允许 LLM 返回多个工具调用
            request_params["tool_choice"] = "auto"

        # 添加额外参数
        for key, value in llm_config.extra_params.items():
            request_params[key] = value

        # 发送请求并获取响应
        # logger.debug(f"发送聊天完成请求到 {llm_config.name}: {request_params}")
        try:
            response = await client.chat.completions.create(**request_params)

            # 使用 TokenUsageTracker 记录 token 使用情况
            cls.token_tracker.record_llm_usage(
                response.usage,
                model_id,
                user_id=agent_context.get_user_id() if agent_context else None,
                model_name=llm_config.name
            )

            return response
        except Exception as e:
            logger.critical(f"调用 LLM {model_id} 时出错: {repr(e)}", exc_info=True)
            raise

    @classmethod
    def get_embedding_client(cls, model_id: str) -> Any:
        """Get an embedding client for the given model ID.

        Args:
            model_id: The model ID to get an embedding client for.

        Returns:
            The embedding client for the given model ID.
        """
        if model_id in cls._clients:
            return cls._clients[model_id]

        if model_id not in cls._configs:
            # 从配置文件中读取模型配置
            model_config = config.get("models", {}).get(model_id)
            if not model_config:
                raise ValueError(f"Unsupported model ID: {model_id}")
            # 过滤 type 不是 embedding 的配置
            if model_config.get("type") != "embedding":
                raise ValueError(f"Model {model_id} is not an Embedding model")

            llm_config = LLMClientConfig(
                model_id=model_id,
                api_key=model_config["api_key"],
                api_base_url=model_config["api_base_url"],
                name=str(model_config["name"]),
                provider=model_config["provider"],
                type=model_config["type"],
                max_output_tokens=model_config.get("max_output_tokens", 4 * 1024),
                max_context_tokens=model_config.get("max_context_tokens", 8 * 1024),
                temperature=model_config.get("temperature", 0.7),
                top_p=model_config.get("top_p", 1.0),
            )
            logger.info(f"创建embedding客户端 - llm_config: {llm_config}")
            cls._configs[model_id] = llm_config

        llm_config = cls._configs[model_id]
        available_providers = ["openai"]
        if llm_config.provider not in available_providers:
            raise ValueError(f"Unsupported provider: {llm_config.provider}")

        if llm_config.provider == "openai":
            client = cls._create_openai_client(llm_config)
            cls._clients[model_id] = client
            return client

    @classmethod
    def get_model_config(cls, model_id: str) -> Dict[str, Any]:
        """Get the model config for the given model ID.

        Args:
            model_id: The model ID to get the config for.

        Returns:
            The model config for the given model ID.
        """
        return cls._configs[model_id]

    @classmethod
    def is_supports_tool_use(cls, model_id: str) -> bool:
        """Check if the model supports tool use.

        Args:
            model_id: The model ID to check.

        Returns:
            True if the model supports tool use, False otherwise.
        """
        return cls._configs[model_id].supports_tool_use

    @classmethod
    def _create_openai_client(cls, llm_config: LLMClientConfig) -> Any:
        """Create an OpenAI client.

        Args:
            model_id: The model ID to create a client for.

        Returns:
            An AsyncOpenAI client.
        """
        # 获取自定义请求头配置
        default_headers = {}

        # 添加Magic-Authorization认证头
        magic_authorization = config.get("sandbox.magic_authorization")
        if magic_authorization:
            default_headers["Magic-Authorization"] = magic_authorization

        # 添加配置文件中定义的自定义请求头（从环境变量读取）
        try:
            custom_headers = config.get("llm.custom_api_headers", {})
            if custom_headers and isinstance(custom_headers, dict):
                # 合并自定义请求头到默认请求头
                default_headers.update(custom_headers)
            else:
                logger.debug("未找到有效的自定义API请求头配置或格式不正确")
        except Exception as e:
            logger.warning(f"处理自定义API请求头配置时出错: {e}", exc_info=True)

        return AsyncOpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.api_base_url,
            timeout=DEFAULT_TIMEOUT,
            max_retries=MAX_RETRIES,
            default_headers=default_headers
        )

    @classmethod
    def get_embedding_dimension(cls, model_id: str) -> int:
        """Get the embedding dimension for the given model ID.

        Args:
            model_id: The model ID to get the embedding dimension for.

        Returns:
            The embedding dimension for the given model ID.
        """
        if model_id not in cls._configs:
            # 从配置文件中读取模型配置
            model_config = config.get("models", {}).get(model_id)
            if not model_config:
                raise ValueError(f"Unsupported model ID: {model_id}")

            llm_config = LLMClientConfig(
                model_id=model_id,
                api_key=model_config["api_key"],
                api_base_url=model_config["api_base_url"],
                name=str(model_config["name"]),
                provider=model_config["provider"],
                type=model_config["type"],
            )
            cls._configs[model_id] = llm_config

        llm_config = cls._configs[model_id]
        model_name = llm_config.name.lower()

        # 根据模型名称返回对应的向量维度
        if "text-embedding-3-large" in model_name:
            return 3072
        elif "text-embedding-3-small" in model_name:
            return 1536
        elif "text-embedding-ada-002" in model_name:
            return 1536
        else:
            # 默认维度为1536
            return 1536

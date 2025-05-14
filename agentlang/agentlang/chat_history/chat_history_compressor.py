# -*- coding: utf-8 -*-
"""
此模块定义了一个用于压缩聊天历史记录的类。
将多轮对话压缩成摘要，以减少token消耗并保持关键信息。
"""

from datetime import datetime
from typing import List, Optional

from agentlang.chat_history.chat_history_models import (
    AssistantMessage,
    ChatMessage,
    CompressionConfig,
    CompressionInfo,
    ToolMessage,
)
from agentlang.context.application_context import ApplicationContext
from agentlang.logger import get_logger

logger = get_logger(__name__)

class ChatHistoryCompressor:
    """
    聊天历史压缩器，用于将多轮对话压缩成摘要。

    此类实现了聊天历史压缩的核心逻辑，包括：
    1. 确定哪些消息需要被压缩
    2. 压缩消息的具体实现
    3. 构建LLM压缩提示
    4. 调用LLM进行压缩
    5. 计算消息的token数量
    """

    def __init__(self, compression_config: CompressionConfig):
        """
        初始化聊天历史压缩器

        Args:
            compression_config: 压缩配置参数
        """
        self.config = compression_config
        self.last_compression_message_count = 0
        self.last_compression_token_count = 0

    def should_compress(self,
                         message_count: int,
                         token_count: int,
                         force: bool = False) -> bool:
        """
        判断是否需要进行压缩

        Args:
            message_count: 当前消息数量
            token_count: 当前token数量
            force: 是否强制压缩，不考虑阈值

        Returns:
            bool: 是否需要压缩
        """
        # 如果压缩功能未启用，直接返回
        if not self.config.enable_compression and not force:
            logger.debug("压缩功能未启用，跳过压缩")
            return False

        # 如果强制压缩，直接返回True
        if force:
            return True

        # 检查是否超过消息数阈值
        need_compression = message_count > self.config.message_threshold
        # 检查是否超过token数阈值
        need_compression = need_compression or (token_count > self.config.token_threshold)

        # 检查是否在冷却期内（上次压缩后消息增量小于冷却值）
        in_cooldown = (
            message_count - self.last_compression_message_count
            < self.config.compression_cooldown
        )
        logger.info(f"{self.config.agent_name} 是否在消息压缩冷却期内: {in_cooldown} ，消息数: {message_count}, 上次压缩后消息增量数: {message_count - self.last_compression_message_count}，冷却值: {self.config.compression_cooldown}")

        # 需要压缩且不在冷却期
        need_compression = need_compression and not in_cooldown

        if not need_compression:
            logger.debug(f"无需压缩：消息数={message_count}，Token数={token_count}，"
                        f"阈值：消息数={self.config.message_threshold}，"
                        f"Token数={self.config.token_threshold}")

        return need_compression

    def _filter_messages_to_compress(self,
                                    all_messages: List[ChatMessage]) -> tuple[List[ChatMessage], List[ChatMessage], List[ChatMessage]]:
        """
        筛选需要压缩的消息和需要保留的消息

        Args:
            all_messages: 所有消息列表

        Returns:
            tuple: (要保留的第一条系统消息, 要压缩的消息列表, 最近的消息列表)
        """
        # 储存 all_messages 到一个 json 文件
        import json
        import os

        # 确保logs目录存在
        path_manager = ApplicationContext.get_path_manager()
        logs_dir = os.path.join(path_manager.get_chat_history_dir(), 'compressed')
        os.makedirs(logs_dir, exist_ok=True)

        # 保存到logs目录
        # 添加时间戳到文件名
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = os.path.join(logs_dir, f'{self.config.agent_name}_{self.config.agent_id}_{timestamp}_messages.json')
        with open(log_file_path, 'w') as f:
            json.dump([msg.to_dict() for msg in all_messages], f, ensure_ascii=False)

        # 直接取前两条消息（不压缩）
        to_preserved = all_messages[:2] if len(all_messages) >= 2 else all_messages.copy()

        # 获取第二条之后的所有消息
        messages_without_to_preserved = all_messages[2:] if len(all_messages) >= 2 else []

        # 筛选所有非系统消息
        to_compress = [
            msg for msg in messages_without_to_preserved
            if msg.role != "system"
        ]

        # 确保保留最近的N轮对话
        preserve_count = min(len(to_compress), self.config.preserve_recent_turns)
        if preserve_count > 0:
            recent_messages = to_compress[-preserve_count:]
            to_compress = to_compress[:-preserve_count]

        # 检查 recent_messages 的第一条是否是 Tool Message，如果是则将它移到 to_compress 的尾部，因为 AssistantMessage with tool_calls 需要与对应的 ToolMessage 在一起
        if recent_messages and isinstance(recent_messages[0], ToolMessage):
            to_compress.append(recent_messages.pop(0))

        return to_preserved, to_compress, recent_messages

    async def compress_messages(self, to_compress: List[ChatMessage], to_preserved: List[ChatMessage]) -> Optional[AssistantMessage]:
        """
        压缩消息。

        Args:
            messages (List[ChatMessage]): 要压缩的消息列表

        Returns:
            Optional[AssistantMessage]: 压缩后的助手消息，如果压缩失败则返回None
        """
        if not to_compress:
            return None

        try:
            # 计算压缩前的token数
            original_tokens = sum(self._count_message_tokens(msg) for msg in to_compress)

            # 创建用于压缩的系统提示
            system_prompt = self._build_compression_system_prompt(to_preserved)

            # 创建用于压缩的用户提示
            user_prompt = self._build_compression_user_prompt(to_compress)

            # 调用LLM进行压缩
            compressed_content = await self._call_llm_for_compression(system_prompt, user_prompt)
            if not compressed_content:
                logger.warning("LLM返回的压缩内容为空")
                return None

            # 创建压缩后的消息
            compressed_message = AssistantMessage(
                content=compressed_content,
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                show_in_ui=False
            )

            # 计算压缩后的token数
            compressed_tokens = self._count_message_tokens(compressed_message)

            # 添加压缩信息
            compressed_message.compression_info = CompressionInfo.create(
                message_count=len(to_compress),
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens
            )

            return compressed_message

        except Exception as e:
            logger.exception(f"压缩消息时出错: {e}")
            return None

    def _build_compression_system_prompt(self, to_preserved: List[ChatMessage]) -> str:
        """
        构建用于压缩的系统提示。

        Returns:
            str: 系统提示内容
        """
        # 只取 to_preserved 中第一条 user message
        user_message = ""
        for msg in to_preserved:
            if msg.role == "user":
                user_message = msg.content
                break
        return f"""你是一个专业的对话压缩助手。你的任务是将多轮对话压缩成一条简洁但信息完整的摘要，同时保留所有关键信息和上下文。

以下是用户的消息，你应该基于用户的需求去提取有效信息：
```
{user_message}
```

在压缩时，请遵循以下原则：
1. 【极其重要】保留用户需求和任务背景的完整信息，尤其是已经尝试过的解决方案、出现的问题以及错误信息
2. 【极其重要】对于重复尝试的内容，必须保留每次尝试的关键步骤、失败原因和尝试的差异点
3. 【极其重要】保留所有关键事实、数据、查询结果、API返回和重要的技术细节、参数设置
4. 【极其重要】保留所有创建文件和修改文件的信息，包括操作类型、文件名、路径、最终的内容
5. 【极其重要】保持对话的完整逻辑流程和因果关系，确保后续操作能理解前面步骤
6. 用简洁的语言替代冗长表达，但绝不简化关键的技术步骤和解决方案
7. 对于代码片段，保留完整的核心功能实现和关键部分，尤其是出错的代码段
8. 对于工具调用，完整保留操作类型、参数和关键结果，简化过程描述
9. 保留所有实体名称、专业术语、技术名词的准确描述，不要进行泛化处理

特别注意：如果发现用户在多次尝试解决同一问题，或者存在循环重试的模式，必须完整保留每次尝试的细节和变化，以免丢失导致重试的关键上下文。对于包含重要决策、断点或转折的对话部分，应当完整保留。

你的回复应该是一个详尽的摘要，不包含任何解释或元描述，直接输出压缩后的内容。宁可少压缩也不要丢失任何可能影响后续对话的关键信息。"""

    def _build_compression_user_prompt(self, messages: List[ChatMessage]) -> str:
        """
        构建用于压缩的用户提示。

        Args:
            messages (List[ChatMessage]): 要压缩的消息列表

        Returns:
            str: 用户提示内容
        """
        # 将消息转换为文本格式
        messages_text = ""
        for msg in messages:
            role = msg.role.upper()
            content = msg.content if msg.content else ""

            # 处理工具调用
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                tool_calls_text = []
                for tool_call in msg.tool_calls:
                    if hasattr(tool_call, 'function') and tool_call.function:
                        func = tool_call.function
                        tool_calls_text.append(f"【调用工具: {func.name}, 参数: {func.arguments}】")
                if tool_calls_text:
                    content += "\n" + "\n".join(tool_calls_text)

            messages_text += f"[{role}]: {content}\n\n"

        # 构建完整提示
        target_ratio = self.config.target_compression_ratio
        prompt = f"""请将以下多轮对话压缩成一条简洁但信息完整的摘要。目标压缩率约为{int(target_ratio*100)}%。

原始对话内容:
{messages_text}

压缩后的摘要(直接输出):"""

        return prompt


    async def _call_llm_for_compression(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        异步调用LLM进行压缩。

        Args:
            system_prompt (str): 系统提示
            user_prompt (str): 用户提示

        Returns:
            Optional[str]: 压缩后的内容，如果失败则返回None
        """
        try:
            from agentlang.llms.factory import LLMFactory

            # 构建LLM请求的消息
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            # 从配置中获取模型ID
            model_id = self.config.llm_for_compression

            logger.info(f"使用模型 {model_id} 进行聊天历史压缩")

            # 调用LLM
            response = await LLMFactory.call_with_tool_support(
                model_id=model_id,
                messages=messages,
                tools=None,
                stop=None
            )

            # 处理响应
            if not response or not hasattr(response, 'choices') or len(response.choices) == 0:
                logger.warning("LLM压缩调用返回空响应")
                return None

            # 提取压缩后的内容
            compressed_content = response.choices[0].message.content

            return compressed_content
        except Exception as e:
            logger.exception(f"调用LLM进行压缩时出错: {e!r}")
            return None

    def _count_message_tokens(self, message) -> int:
        """
        计算单条消息的token数量

        Args:
            message: 需要计算token的消息对象

        Returns:
            int: 消息的token数量
        """
        try:
            # 如果消息已经有token_usage信息，直接使用
            if (hasattr(message, "token_usage") and
                message.token_usage and
                (hasattr(message.token_usage, "completion_tokens") or
                 hasattr(message.token_usage, "prompt_tokens"))):
                # 计算总token数
                total_tokens = 0
                if hasattr(message.token_usage, "completion_tokens"):
                    total_tokens += message.token_usage.completion_tokens or 0
                if hasattr(message.token_usage, "prompt_tokens"):
                    total_tokens += message.token_usage.prompt_tokens or 0
                return total_tokens

            # 否则基于消息内容计算
            import tiktoken

            # 获取编码器，默认使用gpt-3.5-turbo的编码器
            try:
                encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
            except KeyError:
                # 如果模型不存在，使用cl100k_base编码器
                encoding = tiktoken.get_encoding("cl100k_base")

            # 计算消息内容的token数量
            content = message.content or ""

            # 考虑工具调用的token数量
            tool_calls_tokens = 0
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tool_call in message.tool_calls:
                    if hasattr(tool_call, "function") and tool_call.function:
                        # 计算函数名和参数的token
                        function_name = tool_call.function.name or ""
                        function_args = tool_call.function.arguments or "{}"
                        tool_calls_tokens += len(encoding.encode(function_name))
                        tool_calls_tokens += len(encoding.encode(function_args))

            # 总token数 = 内容token + 工具调用token + 基础消息结构token(约4个)
            return len(encoding.encode(content)) + tool_calls_tokens + 4

        except Exception as e:
            # 计算失败时给出警告并返回估计值
            logger.warning(f"计算消息token数量失败: {e!s}")
            # 使用简单的字符数估计，假设每3.5个字符约等于1个token
            content_len = len(message.content or "")
            return max(1, int(content_len / 3.5))

    def update_compression_stats(self, message_count: int, token_count: int) -> None:
        """
        更新压缩状态追踪数据

        Args:
            message_count: 当前消息数量
            token_count: 当前token数量
        """
        self.last_compression_message_count = message_count
        self.last_compression_token_count = token_count

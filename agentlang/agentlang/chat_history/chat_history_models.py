# -*- coding: utf-8 -*-
"""
此模块定义了聊天记录相关的数据结构和模型。
包含消息类型、压缩配置、Token使用信息等与聊天记录相关的类。
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Union

from agentlang.config.config import config
from agentlang.llms.token_usage.models import TokenUsage  # 导入统一的 TokenUsage 类
from agentlang.logger import get_logger

logger = get_logger(__name__)

# ==============================================================================
# 压缩配置数据类
# ==============================================================================
@dataclass
class CompressionConfig:
    """聊天历史压缩功能的配置类"""
    # 基础开关配置
    enable_compression: bool = True  # 是否启用压缩功能

    # 基础 Agent 信息
    agent_name: str = ""
    agent_id: str = ""
    agent_model_id: str = ""
    # 触发阈值配置
    token_threshold: int = 0  # 触发压缩的token数阈值，默认设置为0，将根据模型动态计算
    message_threshold: int = 100  # 消息数量阈值
    preserve_recent_turns: int = 20  # 保留不压缩的最近对话轮数
    # 消息压缩配置
    target_compression_ratio: float = 0.6  # 总体目标压缩率

    # 高级配置
    compression_cooldown: int = 6  # 两次压缩间隔的最小消息数
    compression_batch_size: int = 10  # 每批压缩的最大消息数
    llm_for_compression: str = "gpt-4.1-mini"  # 用于压缩的LLM模型
    def __post_init__(self):
        """参数验证和规范化"""
        # 验证压缩率范围
        if not 0 <= self.target_compression_ratio <= 1:
            raise ValueError("总体目标压缩率必须在 0-1 之间")

        # 验证阈值和保留轮数
        if self.message_threshold < 0:
            raise ValueError("消息数量阈值不能为负数")
        if self.preserve_recent_turns < 0:
            raise ValueError("保留的对话轮数不能为负数")

        # 如果token_threshold为0，根据当前使用的模型上下文长度设置默认值
        if self.token_threshold <= 0:
            self.token_threshold = self._calculate_model_based_threshold()
            logger.info(f"根据当前 Agent 使用的 {self.agent_model_id} 模型的上下文长度设置压缩上下文的 token_threshold 为: {self.token_threshold}")

    def _calculate_model_based_threshold(self) -> int:
        """
        根据模型的上下文长度计算适当的token阈值

        Returns:
            int: 计算得到的token阈值
        """
        try:
            # 获取模型信息
            threshold = 40000  # 默认阈值

            # 获取所有模型配置
            model_configs = config.get("models", {})

            if self.agent_model_id:
                # 从模型配置中获取max_context_tokens
                model_config = model_configs.get(self.agent_model_id, {})
                max_context_tokens = int(model_config.get("max_context_tokens", 0))
                # 设置为上下文长度的70%作为阈值
                threshold = int(max_context_tokens * 0.7)

            return threshold

        except Exception as e:
            logger.error(f"设置token阈值时出错: {e}")
            return 160000  # 出错时返回默认值

# ==============================================================================
# 压缩信息元数据
# ==============================================================================
@dataclass
class CompressionInfo:
    """聊天消息压缩相关的元数据"""
    is_compressed: bool = False  # 是否为压缩后的消息
    original_message_count: int = 0  # 原始消息数量
    compression_ratio: float = 0.0  # 实际压缩率
    compressed_at: str = ""  # 压缩时间
    message_spans: List[Dict[str, str]] = field(default_factory=list)  # 原始消息的时间跨度

    @classmethod
    def create(cls, message_count: int, original_tokens: int, compressed_tokens: int) -> 'CompressionInfo':
        """
        创建压缩信息实例

        Args:
            message_count: 被压缩的原始消息数量
            original_tokens: 压缩前的token数
            compressed_tokens: 压缩后的token数

        Returns:
            CompressionInfo: 压缩信息实例
        """
        compression_ratio = 1.0
        if original_tokens > 0:
            compression_ratio = 1.0 - (compressed_tokens / original_tokens)

        # 将压缩率限制在0-1之间
        compression_ratio = max(0.0, min(1.0, compression_ratio))

        return cls(
            is_compressed=True,
            original_message_count=message_count,
            compression_ratio=compression_ratio,
            compressed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

    def to_dict(self) -> Dict[str, Any]:
        """将压缩信息转换为字典格式"""
        result = {
            "is_compressed": self.is_compressed,
            "original_message_count": self.original_message_count,
            "compression_ratio": self.compression_ratio,
            "compressed_at": self.compressed_at,
        }

        if self.message_spans:
            result["message_spans"] = self.message_spans

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CompressionInfo':
        """从字典创建压缩信息对象"""
        compression_info = cls(
            is_compressed=data.get("is_compressed", False),
            original_message_count=data.get("original_message_count", 0),
            compression_ratio=data.get("compression_ratio", 0.0),
            compressed_at=data.get("compressed_at", ""),
        )

        spans = data.get("message_spans")
        if spans and isinstance(spans, list):
            compression_info.message_spans = spans

        return compression_info

# ==============================================================================
# 辅助函数：耗时格式化与解析
# ==============================================================================

def format_duration_to_str(duration_ms: Optional[float]) -> Optional[str]:
    """
    将毫秒数 (float) 格式化为人类可读的字符串 (方案二: HhMmS.fffS)。

    Args:
        duration_ms (Optional[float]): 耗时，单位毫秒。

    Returns:
        Optional[str]: 格式化后的字符串，或 None。
    """
    if duration_ms is None or duration_ms < 0:
        return None

    try:
        # 创建 timedelta 对象 (注意 timedelta 使用秒)
        delta = timedelta(milliseconds=duration_ms)

        total_seconds = delta.total_seconds()
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        hours = int(hours)
        minutes = int(minutes)
        # 秒数保留毫秒精度
        seconds_float = seconds

        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")

        # 秒数部分始终显示，并格式化为 xxx.fff
        # 使用 Decimal 或精确计算避免浮点误差，但这里简单处理应该足够
        parts.append(f"{seconds_float:.3f}s")

        return "".join(parts)

    except Exception as e:
        logger.warning(f"格式化耗时 {duration_ms}ms 时出错: {e}")
        return None

def parse_duration_from_str(duration_str: Optional[str]) -> Optional[float]:
    """
    从人类可读的字符串 (方案二: HhMmS.fffS) 解析回毫秒数 (float)。

    Args:
        duration_str (Optional[str]): 格式化的耗时字符串。

    Returns:
        Optional[float]: 耗时，单位毫秒，或 None (如果解析失败)。
    """
    if not duration_str or not isinstance(duration_str, str):
        return None

    total_milliseconds = 0.0
    pattern = re.compile(r"(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>[\d.]+)s)?")
    match = pattern.fullmatch(duration_str)

    if not match:
        logger.warning(f"无法解析耗时字符串格式: {duration_str}")
        return None

    try:
        data = match.groupdict()
        if data["hours"]:
            total_milliseconds += float(data["hours"]) * 3600 * 1000
        if data["minutes"]:
            total_milliseconds += float(data["minutes"]) * 60 * 1000
        if data["seconds"]:
            total_milliseconds += float(data["seconds"]) * 1000

        return total_milliseconds
    except (ValueError, TypeError) as e:
        logger.warning(f"解析耗时字符串 {duration_str} 时数值转换错误: {e}")
        return None
    except Exception as e:
        logger.error(f"解析耗时字符串 {duration_str} 时未知错误: {e}", exc_info=True)
        return None


# ==============================================================================
# 数据类定义 (参考 openai.types.chat)
# ==============================================================================

@dataclass
class FunctionCall:
    """
    表示模型请求的函数调用信息。
    参考: openai.types.chat.ChatCompletionMessageToolCall.Function
    """
    name: str  # 要调用的函数名称
    arguments: str  # 函数参数，JSON格式的字符串

    def to_dict(self) -> Dict[str, Any]:
        """将函数调用信息转换为字典格式"""
        return {
            "name": self.name,
            "arguments": self.arguments
        }


@dataclass
class ToolCall:
    """
    表示模型生成的工具调用请求。
    参考: openai.types.chat.ChatCompletionMessageToolCall
    """
    id: str  # 工具调用的唯一标识符
    type: Literal["function"] = "function"  # 工具类型，目前仅支持 'function'
    function: FunctionCall = None # 函数调用详情

    def to_dict(self) -> Dict[str, Any]:
        """将工具调用信息转换为字典格式"""
        return {
            "id": self.id,
            "type": self.type,
            "function": self.function.to_dict() if self.function else None
        }


@dataclass
class SystemMessage:
    """系统消息"""
    content: str # 系统消息内容，不能为空
    role: Literal["system"] = "system"
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    show_in_ui: bool = True # <--- 重命名并设置默认值

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(uuid.uuid4()), # 运行时 ID
            "timestamp": self.created_at,
            "role": self.role,
            "content": self.content,
            "show_in_ui": self.show_in_ui,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemMessage":
        """从字典创建系统消息对象"""
        return cls(
            content=data.get("content", " "), # 确保有内容
            role=data.get("role", "system"),
            show_in_ui=data.get("show_in_ui", True),
            created_at=data.get("timestamp", datetime.now().isoformat()),
        )


@dataclass
class UserMessage:
    """用户消息"""
    content: str # 用户消息内容，不能为空
    role: Literal["user"] = "user"
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    show_in_ui: bool = True # <--- 重命名并设置默认值

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(uuid.uuid4()), # 运行时 ID
            "timestamp": self.created_at,
            "role": self.role,
            "content": self.content,
            "show_in_ui": self.show_in_ui,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMessage":
        """从字典创建用户消息对象"""
        return cls(
            content=data.get("content", " "), # 确保有内容
            role=data.get("role", "user"),
            show_in_ui=data.get("show_in_ui", True),
            created_at=data.get("timestamp", datetime.now().isoformat()),
        )


@dataclass
class AssistantMessage:
    """助手消息 (模型的回应)"""
    content: Optional[str] = None # 助手消息内容。可以为 None 或空，当且仅当 tool_calls 存在。
    role: Literal["assistant"] = "assistant"
    tool_calls: Optional[List[ToolCall]] = None # 模型请求的工具调用列表
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    show_in_ui: bool = True # <--- 重命名并设置默认值 (finish_task 会在 append 时设为 False)
    duration_ms: Optional[float] = None # 内部存储为毫秒 float
    # --- 使用统一的 TokenUsage 类型 ---
    token_usage: Optional[TokenUsage] = None
    # --- 新增压缩相关字段 ---
    compression_info: Optional[CompressionInfo] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": str(uuid.uuid4()), # 运行时 ID
            "timestamp": self.created_at,
            "role": self.role,
            "content": self.content,
            "show_in_ui": self.show_in_ui,
            "duration_ms": self.duration_ms, # 注意：这个字段在 save 时会被移除，转换成 duration 字符串
        }

        # 处理 token_usage
        if self.token_usage:
            result["token_usage"] = self.token_usage.to_dict()

        # 只有当 compression_info 不为 None 时才添加
        if self.compression_info:
            result["compression_info"] = self.compression_info.to_dict()

        if self.tool_calls:
            result["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]

        # 清理值为 None 的顶级键 (除了 content 和 tool_calls，因为 assistant 可以只有其中一个)
        result = {k: v for k, v in result.items() if v is not None or k in ['content', 'tool_calls']}

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssistantMessage":
        msg = cls(
            content=data.get("content"), # 允许为 None
            role=data.get("role", "assistant"),
            show_in_ui=data.get("show_in_ui", True),
            duration_ms=data.get("duration_ms"),
            created_at=data.get("timestamp", datetime.now().isoformat()),
        )

        # --- 解析 token_usage ---
        token_usage_data = data.get("token_usage")
        if token_usage_data and isinstance(token_usage_data, dict):
            try:
                # 直接使用 from_response 方法处理，由它自动适配各种格式
                token_usage_obj = TokenUsage.from_response(token_usage_data)
                msg.token_usage = token_usage_obj
            except Exception as e:
                logger.warning(f"加载历史时解析 token_usage 失败: {token_usage_data}, 错误: {e}")

        # --- 解析 compression_info ---
        compression_info_data = data.get("compression_info")
        if compression_info_data and isinstance(compression_info_data, dict):
            try:
                compression_info_obj = CompressionInfo.from_dict(compression_info_data)
                # 只有 is_compressed 为 True 的才保留
                if compression_info_obj and compression_info_obj.is_compressed:
                    msg.compression_info = compression_info_obj
                else:
                     logger.debug(f"加载时跳过空的或未压缩的 compression_info: {compression_info_data}")
            except Exception as e:
                logger.warning(f"加载历史时解析 compression_info 失败: {compression_info_data}, 错误: {e}")

        # --- 解析 tool_calls ---
        tool_calls_data = data.get("tool_calls")
        if tool_calls_data and isinstance(tool_calls_data, list):
            msg.tool_calls = []
            for tc_data in tool_calls_data:
                if isinstance(tc_data, dict):
                    try:
                        function_data = tc_data.get("function", {})
                        # 确保 arguments 是字符串
                        arguments_raw = function_data.get("arguments")
                        arguments_str = arguments_raw if isinstance(arguments_raw, str) else json.dumps(arguments_raw or {})

                        function_call = FunctionCall(
                            name=function_data.get("name", ""),
                            arguments=arguments_str
                        )
                        tool_call = ToolCall(
                            id=tc_data.get("id", str(uuid.uuid4())),
                            type=tc_data.get("type", "function"),
                            function=function_call
                        )
                        # 基本验证
                        if tool_call.id and tool_call.function and tool_call.function.name:
                            msg.tool_calls.append(tool_call)
                        else:
                            logger.warning(f"加载时跳过无效的 tool_call 结构 (缺少 id 或 function.name): {tc_data}")
                    except Exception as e:
                         logger.warning(f"加载时解析 tool_call 失败: {tc_data}, 错误: {e}")

        return msg


@dataclass
class ToolMessage:
    """工具执行结果消息"""
    content: str # 工具执行结果内容，不能为空
    tool_call_id: str # 对应的工具调用 ID
    role: Literal["tool"] = "tool"
    system: Optional[str] = None # 内部使用的系统标志，例如标记中断
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    show_in_ui: bool = True # <--- 重命名并设置默认值 (中断提示会在 append 时设为 False)
    duration_ms: Optional[float] = None # 内部存储为毫秒 float

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": str(uuid.uuid4()), # 运行时 ID
            "timestamp": self.created_at,
            "role": self.role,
            "content": self.content,
            "tool_call_id": self.tool_call_id,
            "system": self.system,
            "show_in_ui": self.show_in_ui,
            "duration_ms": self.duration_ms, # 注意：这个字段在 save 时会被移除
        }
        # 清理值为 None 的顶级键 (system, duration_ms 可能为 None)
        return {k: v for k, v in result.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolMessage":
        """从字典创建工具消息对象"""
        return cls(
            content=data.get("content", " "), # 确保有内容
            tool_call_id=data.get("tool_call_id", ""), # ID 不能为空，后续 validate 会检查
            role=data.get("role", "tool"),
            system=data.get("system"), # 可以为 None
            show_in_ui=data.get("show_in_ui", True),
            duration_ms=data.get("duration_ms"), # 可以为 None
            created_at=data.get("timestamp", datetime.now().isoformat()),
        )


# 所有可能的消息类型的联合类型
ChatMessage = Union[SystemMessage, UserMessage, AssistantMessage, ToolMessage]

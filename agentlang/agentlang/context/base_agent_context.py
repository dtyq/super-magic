"""
基础代理上下文类

提供代理上下文基本功能的实现，不包含业务逻辑
"""

import asyncio
import os
from typing import Any, Callable, Dict, Optional

from agentlang.context.base_context import BaseContext
from agentlang.context.shared_context import AgentSharedContext
from agentlang.event.dispatcher import EventDispatcher
from agentlang.event.interface import EventDispatcherInterface
from agentlang.interface.context import AgentContextInterface
from agentlang.logger import get_logger

logger = get_logger(__name__)

class BaseAgentContext(BaseContext, AgentContextInterface):
    """基础代理上下文实现
    
    提供核心接口的基本实现，不包含业务逻辑
    """

    _workspace_dir: str
    _resources: Dict[str, Any]
    _user_id: Optional[str]

    def __init__(self):
        """初始化基础代理上下文"""
        super().__init__()
        # 使用已存在的单例实例而非尝试创建新实例
        self.shared_context = AgentSharedContext

        self._workspace_dir = ""
        self._resources: Dict[str, Any] = {}
        self._user_id = None

        # 框架层基础属性
        self.agent_name = "base_agent"  # 默认代理名称
        self.is_main_agent = False  # 是否为主代理
        self.stream_mode = False  # 流模式开关
        self.llm = None  # 当前使用的LLM模型
        self.use_dynamic_prompt = True  # 动态提示词开关
        self.chat_history_dir = ""  # 聊天历史目录

    def _init_shared_fields(self):
        """初始化共享字段并注册到 shared_context"""
        # 检查是否已经初始化
        if self.shared_context.has_field("event_dispatcher"):
            return

        self.shared_context.register_fields({
            "event_dispatcher": (EventDispatcher(), EventDispatcherInterface),
        })

    def get_workspace_dir(self) -> str:
        """获取工作空间目录"""
        return self._workspace_dir

    def set_workspace_dir(self, workspace_dir: str) -> None:
        """设置工作空间目录"""
        self._workspace_dir = workspace_dir
        logger.debug(f"设置工作空间目录: {workspace_dir}")

    def ensure_workspace_dir(self) -> str:
        """确保工作空间目录存在"""
        if not self._workspace_dir:
            raise ValueError("工作空间目录未设置")

        os.makedirs(self._workspace_dir, exist_ok=True)
        return self._workspace_dir

    def set_agent_name(self, agent_name: str) -> None:
        """设置代理名称
        
        Args:
            agent_name: 代理名称
        """
        self.agent_name = agent_name
        logger.debug(f"设置代理名称: {agent_name}")

    def get_agent_name(self) -> str:
        """获取代理名称"""
        return self.agent_name

    def set_main_agent(self, is_main: bool) -> None:
        """设置是否为主代理
        
        Args:
            is_main: 是否为主代理
        """
        self.is_main_agent = is_main
        logger.debug(f"设置是否为主代理: {is_main}")

    def is_main_agent(self) -> bool:
        """获取是否为主代理"""
        return self.is_main_agent

    def set_stream_mode(self, enabled: bool) -> None:
        """设置是否使用流式输出
        
        Args:
            enabled: 是否启用
        """
        self.stream_mode = enabled
        logger.debug(f"设置流式输出模式: {enabled}")

    def is_stream_mode(self) -> bool:
        """获取流式输出模式"""
        return self.stream_mode

    def set_llm(self, model: str) -> None:
        """设置LLM模型
        
        Args:
            model: 模型名称
        """
        self.llm = model
        logger.debug(f"设置LLM模型: {model}")

    def get_llm(self) -> str:
        """获取LLM模型"""
        return self.llm

    def set_use_dynamic_prompt(self, enabled: bool) -> None:
        """设置是否使用动态提示词
        
        Args:
            enabled: 是否启用
        """
        self.use_dynamic_prompt = enabled
        logger.debug(f"设置动态提示词: {enabled}")

    def is_use_dynamic_prompt(self) -> bool:
        """获取是否使用动态提示词"""
        return self.use_dynamic_prompt

    def set_chat_history_dir(self, directory: str) -> None:
        """设置聊天历史目录
        
        Args:
            directory: 聊天历史目录路径
        """
        self.chat_history_dir = directory
        os.makedirs(directory, exist_ok=True)
        logger.debug(f"设置聊天历史目录: {directory}")

    def get_chat_history_dir(self) -> str:
        """获取聊天历史目录"""
        return self.chat_history_dir

    def get_event_dispatcher(self) -> EventDispatcherInterface:
        """获取事件分发器

        Returns:
            EventDispatcherInterface: 事件分发器
        """
        return self.shared_context.get_field("event_dispatcher")


    async def dispatch_event(self, event_type: str, data: Any) -> Any:
        """分发事件"""
        from agentlang.event.event import Event
        event = Event(event_type, data)
        logger.debug(f"分发事件: {event_type}")
        return await self.get_event_dispatcher().dispatch(event)

    def add_event_listener(self, event_type: str, listener: Callable) -> None:
        """添加事件监听器"""
        self.get_event_dispatcher().add_listener(event_type, listener)
        logger.debug(f"添加事件监听器: {event_type}")

    async def get_resource(self, name: str, factory=None) -> Any:
        """获取资源，如不存在则创建"""
        # 资源不存在且提供了工厂函数，则创建
        if name not in self._resources and factory is not None:
            try:
                # 如果工厂是异步函数，等待其完成
                if asyncio.iscoroutinefunction(factory):
                    self._resources[name] = await factory()
                else:
                    self._resources[name] = factory()
                logger.debug(f"创建资源: {name}")
            except Exception as e:
                logger.error(f"创建资源 {name} 时出错: {e}")
                raise RuntimeError(f"创建资源 {name} 时出错: {e}")

        # 返回资源（可能为None）
        return self._resources.get(name)

    def add_resource(self, name: str, resource: Any) -> None:
        """添加资源"""
        self._resources[name] = resource
        logger.debug(f"添加资源: {name}")

    async def close_resource(self, name: str) -> None:
        """关闭并移除资源"""
        if name not in self._resources:
            return

        resource = self._resources[name]
        try:
            # 尝试关闭资源（如果它有close方法）
            if hasattr(resource, "close") and callable(getattr(resource, "close")):
                if asyncio.iscoroutinefunction(resource.close):
                    await resource.close()
                else:
                    resource.close()
                logger.debug(f"关闭资源: {name}")

            # 移除资源
            del self._resources[name]
        except Exception as e:
            logger.error(f"关闭资源 {name} 时出错: {e}")
            # 尽管出错，仍然从字典中移除
            if name in self._resources:
                del self._resources[name]
            raise RuntimeError(f"关闭资源 {name} 时出错: {e}")

    async def close_all_resources(self) -> None:
        """关闭并移除所有资源"""
        # 复制键列表，因为在迭代过程中会修改字典
        resource_names = list(self._resources.keys())
        for name in resource_names:
            await self.close_resource(name)
        logger.debug(f"关闭所有资源 ({len(resource_names)} 个)")

    def set_user_id(self, user_id: str) -> None:
        """设置用户ID"""
        self._user_id = user_id

    def get_user_id(self) -> Optional[str]:
        """获取用户ID"""
        return self._user_id

    def get_metadata(self) -> Dict[str, Any]:
        """获取上下文元数据
        
        继承自BaseContext，返回所有元数据
        """
        return {**self._metadata} 

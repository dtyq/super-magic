"""
代理上下文接口

定义获取用户信息和基础功能的抽象接口，用于解耦框架与具体实现
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, TypeVar

T = TypeVar('T')  # 用于泛型类型

class AgentContextInterface(ABC):
    """
    代理上下文基础接口
    
    定义框架层必要的核心功能，包括用户信息、工作空间、事件系统和资源管理
    """
    
    @abstractmethod
    def get_user_id(self) -> Optional[str]:
        """获取用户ID
        
        Returns:
            Optional[str]: 用户ID，如果不存在则返回None
        """
        pass
        
    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """获取元数据
        
        Returns:
            Dict[str, Any]: 上下文元数据
        """
        pass
    
    @abstractmethod
    def get_workspace_dir(self) -> str:
        """获取工作空间目录
        
        Returns:
            str: 工作空间目录的绝对路径
        """
        pass
    
    @abstractmethod
    def ensure_workspace_dir(self) -> str:
        """确保工作空间目录存在，并返回路径
        
        Returns:
            str: 工作空间目录的绝对路径
        """
        pass
        
    @abstractmethod
    async def dispatch_event(self, event_type: str, data: Any) -> Any:
        """分发事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
            
        Returns:
            Any: 事件处理结果
        """
        pass
    
    @abstractmethod
    def add_event_listener(self, event_type: str, listener: Callable[[Any], None]) -> None:
        """添加事件监听器
        
        Args:
            event_type: 事件类型
            listener: 事件监听函数，接收一个事件参数
        """
        pass
    
    @abstractmethod
    async def get_resource(self, name: str, factory=None) -> Any:
        """获取资源，如不存在则使用工厂创建
        
        Args:
            name: 资源名称
            factory: 资源创建工厂函数，仅在资源不存在时调用
            
        Returns:
            Any: 请求的资源实例
        """
        pass
    
    @abstractmethod
    def add_resource(self, name: str, resource: Any) -> None:
        """添加资源
        
        Args:
            name: 资源名称
            resource: 资源实例
        """
        pass
    
    @abstractmethod
    async def close_resource(self, name: str) -> None:
        """关闭并移除资源
        
        Args:
            name: 资源名称
        """
        pass 
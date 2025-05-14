"""
异常定义模块

本模块包含所有 agentlang 包使用的异常类定义，
提供了统一的异常处理接口和用户友好的消息展示机制。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class UserFriendlyException(BaseException, ABC):
    """用户友好异常接口类
    
    定义了可以向用户展示友好错误消息的异常接口。
    继承此类的异常应实现 get_user_friendly_message 方法，
    以提供适合直接展示给最终用户的错误消息。
    """
    
    def __init__(self, message: str = "", **kwargs: Any):
        """初始化异常
        
        Args:
            message: 异常消息
            **kwargs: 其他异常相关参数
        """
        self.message = message
        self.extra_data: Dict[str, Any] = kwargs
        super().__init__(message)
    
    @abstractmethod
    def get_user_friendly_message(self) -> str:
        """获取适合向用户展示的友好错误消息
        
        返回一个经过格式化、便于理解的错误消息，
        该消息可以直接展示给最终用户，无需技术背景也能理解。
        
        Returns:
            str: 格式化后的用户友好消息
        """
        pass 
"""
事件系统公共类定义

提供基础的事件数据模型和类型定义，用于打破循环依赖
"""

from pydantic import BaseModel, ConfigDict


class BaseEventData(BaseModel):
    """事件数据基类，所有事件数据模型都应继承此类"""

    model_config = ConfigDict(arbitrary_types_allowed=True) 

# 定义代理状态枚举
import enum

class AgentState(enum.Enum):
    """Agent状态枚举"""

    IDLE = "idle"  # 空闲状态
    RUNNING = "running"  # 运行中
    FINISHED = "finished"  # 顺利完成状态
    ERROR = "error"  # 错误状态 
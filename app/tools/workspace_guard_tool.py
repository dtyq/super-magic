from pathlib import Path
from typing import Optional, TypeVar

from agentlang.context.tool_context import ToolContext
from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from app.paths import PathManager
from app.tools.core.base_tool import BaseTool
from app.tools.core.base_tool_params import BaseToolParams

logger = get_logger(__name__)

# 定义参数类型变量
T = TypeVar('T', bound=BaseToolParams)


class WorkspaceGuardTool(BaseTool[T]):
    """
    文件操作工具基类，提供工作目录限制和相关安全功能

    所有需要访问文件系统的工具都应继承此类，以便统一处理工作目录限制
    """

    # 默认使用workspace目录作为基础目录
    base_dir: Path = PathManager.get_workspace_dir()

    def __init__(self, **data):
        """
        初始化文件操作工具

        Args:
            **data: 其他参数传递给父类
        """
        super().__init__(**data)
        if 'base_dir' in data:
            self.base_dir = Path(data['base_dir'])

    def get_safe_path(self, filepath: str) -> tuple[Path, Optional[str]]:
        """
        获取安全的文件路径，确保其在工作目录内

        Args:
            filepath: 文件路径字符串

        Returns:
            tuple: (安全的文件路径对象, 错误信息)
                如果路径安全，错误信息为空字符串
                如果路径不安全，返回None和对应的错误信息
        """
        # 处理文件路径
        file_path = Path(filepath)

        # 如果是相对路径，则相对于base_dir
        if not file_path.is_absolute():
            file_path = self.base_dir / file_path

        # 检查文件是否在base_dir内
        try:
            file_path.relative_to(self.base_dir)
            return file_path, ""
        except ValueError:
            error_msg = f"安全限制：不允许访问工作目录({self.base_dir})外的文件: {file_path}"
            logger.warning(error_msg)
            return None, error_msg

    async def execute(self, tool_context: ToolContext, params: T) -> ToolResult:
        """
        默认执行方法，子类应该重写此方法

        Args:
            tool_context: 工具上下文
            params: 工具参数

        Returns:
            ToolResult: 工具执行结果
        """
        raise NotImplementedError("子类必须实现execute方法")

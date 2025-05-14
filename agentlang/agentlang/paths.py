"""
路径相关的常量和工具函数，使用面向对象方式实现
"""

from pathlib import Path
from typing import Optional, ClassVar

class PathManager:
    """
    路径管理器，提供项目中核心且通用的路径访问
    使用静态方法实现，不需要实例化
    """

    # 静态类变量 - 核心目录
    _project_root: ClassVar[Optional[Path]] = None
    _logs_dir_name: ClassVar[str] = "logs"
    _logs_dir: ClassVar[Optional[Path]] = None
    _workspace_dir_name: ClassVar[str] = ".workspace"
    _workspace_dir: ClassVar[Optional[Path]] = None
    _browser_data_dir_name: ClassVar[str] = ".browser"
    _browser_data_dir: ClassVar[Optional[Path]] = None
    _cache_dir_name: ClassVar[str] = "cache"
    _cache_dir: ClassVar[Optional[Path]] = None
    _chat_history_dir_name: ClassVar[str] = ".chat_history"  # 使用应用层建议的顶级带点目录
    _chat_history_dir: ClassVar[Optional[Path]] = None

    _initialized: ClassVar[bool] = False

    @classmethod
    def set_project_root(cls, project_root: Path) -> None:
        """
        设置项目根目录并初始化所有核心路径

        Args:
            project_root: 项目根目录路径
        """
        if cls._initialized:
            return

        cls._project_root = project_root

        # 初始化所有核心路径
        cls._logs_dir = cls._project_root / cls._logs_dir_name
        cls._workspace_dir = cls._project_root / cls._workspace_dir_name
        cls._browser_data_dir = cls._project_root / cls._browser_data_dir_name
        cls._cache_dir = cls._project_root / cls._cache_dir_name
        cls._chat_history_dir = cls._project_root / cls._chat_history_dir_name

        # 确保必要的目录存在
        cls._ensure_directories_exist()

        cls._initialized = True

    @classmethod
    def _ensure_directories_exist(cls) -> None:
        """确保所有核心目录存在"""
        if cls._project_root is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")

        cls._logs_dir.mkdir(exist_ok=True)
        cls._workspace_dir.mkdir(exist_ok=True)
        cls._browser_data_dir.mkdir(exist_ok=True)
        cls._cache_dir.mkdir(exist_ok=True)
        cls._chat_history_dir.mkdir(exist_ok=True)

    @classmethod
    def get_project_root(cls) -> Path:
        """获取项目根目录路径"""
        if cls._project_root is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._project_root

    @classmethod
    def get_logs_dir_name(cls) -> str:
        """获取日志目录名称"""
        return cls._logs_dir_name

    @classmethod
    def get_logs_dir(cls) -> Path:
        """获取日志目录路径"""
        if cls._logs_dir is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._logs_dir

    @classmethod
    def get_workspace_dir_name(cls) -> str:
        """获取工作空间目录名称"""
        return cls._workspace_dir_name

    @classmethod
    def get_workspace_dir(cls) -> Path:
        """获取工作空间目录路径"""
        if cls._workspace_dir is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._workspace_dir

    @classmethod
    def get_browser_data_dir_name(cls) -> str:
        """获取浏览器数据目录名称"""
        return cls._browser_data_dir_name

    @classmethod
    def get_browser_data_dir(cls) -> Path:
        """获取浏览器数据目录路径"""
        if cls._browser_data_dir is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._browser_data_dir

    @classmethod
    def get_cache_dir_name(cls) -> str:
        """获取缓存目录名称"""
        return cls._cache_dir_name

    @classmethod
    def get_cache_dir(cls) -> Path:
        """获取缓存目录路径"""
        if cls._cache_dir is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._cache_dir

    @classmethod
    def get_chat_history_dir_name(cls) -> str:
        """获取聊天历史记录目录名称"""
        return cls._chat_history_dir_name

    @classmethod
    def get_chat_history_dir(cls) -> Path:
        """获取聊天历史记录目录路径"""
        if cls._chat_history_dir is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._chat_history_dir

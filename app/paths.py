"""
路径相关的常量和工具函数，使用面向对象方式实现
"""

from pathlib import Path
from typing import Optional, ClassVar

from agentlang.paths import PathManager as BasePathManager

class PathManager(BasePathManager):
    """
    应用层路径管理器，继承自基础框架并添加应用特有路径
    """

    # 浏览器存储状态文件
    _browser_storage_state_file: ClassVar[Optional[Path]] = None

    # 凭证目录
    _credentials_dir_name: ClassVar[str] = ".credentials"
    _credentials_dir: ClassVar[Optional[Path]] = None
    _init_client_message_file: ClassVar[Optional[Path]] = None

    # 项目架构目录
    _project_schema_dir_name: ClassVar[str] = ".project_schemas"
    _project_schema_absolute_dir: ClassVar[Optional[Path]] = None

    # 项目归档目录
    _project_archive_dir_name: ClassVar[str] = "project_archive"
    _project_archive_info_file_relative_path: ClassVar[Optional[str]] = None
    _project_archive_info_file: ClassVar[Optional[Path]] = None

    @classmethod
    def set_project_root(cls, project_root: Path) -> None:
        """
        设置项目根目录并初始化所有路径（框架层 + 应用层）

        Args:
            project_root: 项目根目录路径
        """
        super().set_project_root(project_root)

        cls._credentials_dir = cls._project_root.joinpath(cls._credentials_dir_name)
        cls._browser_storage_state_file = cls.get_browser_data_dir() / "storage_state.json"
        cls._init_client_message_file = cls.get_credentials_dir() / "init_client_message.json"
        cls._project_schema_absolute_dir = cls._project_root / cls._project_schema_dir_name
        cls._project_archive_info_file_relative_path = f"{cls._project_schema_dir_name}/project_archive_info.json"
        cls._project_archive_info_file = cls.get_project_schema_absolute_dir() / "project_archive_info.json"

        # 确保应用层特有的目录存在
        cls._ensure_app_directories_exist()

    @classmethod
    def _ensure_app_directories_exist(cls) -> None:
        """确保应用层特有的目录存在 (核心目录由框架层保证)"""
        if cls._project_root is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")

        # 只创建应用层自己管理的目录
        cls._credentials_dir.mkdir(exist_ok=True)
        cls._project_schema_absolute_dir.mkdir(exist_ok=True)

    # 应用层特有路径的 getter 方法

    @classmethod
    def get_browser_storage_state_file(cls) -> Path:
        """获取浏览器存储状态文件路径"""
        if cls._browser_storage_state_file is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._browser_storage_state_file

    @classmethod
    def get_project_archive_dir_name(cls) -> str:
        """获取项目归档目录名称"""
        return cls._project_archive_dir_name

    @classmethod
    def get_credentials_dir_name(cls) -> str:
        """获取凭证目录名称"""
        return cls._credentials_dir_name

    @classmethod
    def get_credentials_dir(cls) -> Path:
        """获取凭证目录路径"""
        if cls._credentials_dir is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._credentials_dir

    @classmethod
    def get_init_client_message_file(cls) -> Path:
        """获取初始客户端消息文件路径"""
        if cls._init_client_message_file is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._init_client_message_file

    @classmethod
    def get_project_schema_dir_name(cls) -> str:
        """获取项目架构目录名称"""
        return cls._project_schema_dir_name

    @classmethod
    def get_project_schema_absolute_dir(cls) -> Path:
        """获取项目架构绝对目录路径"""
        if cls._project_schema_absolute_dir is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._project_schema_absolute_dir

    @classmethod
    def get_project_archive_info_file_relative_path(cls) -> str:
        """获取项目归档信息文件相对路径"""
        if cls._project_archive_info_file_relative_path is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._project_archive_info_file_relative_path

    @classmethod
    def get_project_archive_info_file(cls) -> Path:
        """获取项目归档信息文件路径"""
        if cls._project_archive_info_file is None:
            raise RuntimeError("必须先调用 set_project_root 设置项目根目录")
        return cls._project_archive_info_file

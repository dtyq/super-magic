from logging import Logger
from typing import ClassVar
from agentlang.paths import PathManager


class ApplicationContext:

    _logger: ClassVar[Logger] = None
    _path_manager: ClassVar[PathManager] = None

    @classmethod
    def set_logger(cls, logger: Logger):
        cls._logger = logger

    @classmethod
    def get_logger(cls) -> Logger:
        return cls._logger

    @classmethod
    def set_path_manager(cls, path_manager: PathManager):
        cls._path_manager = path_manager

    @classmethod
    def get_path_manager(cls) -> PathManager:
        return cls._path_manager

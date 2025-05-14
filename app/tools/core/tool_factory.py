"""工具工厂模块

负责工具的自动发现、注册和创建
"""

import importlib
import importlib.metadata
import inspect
import os
import pkgutil
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Type, TypeVar

from agentlang.context.tool_context import ToolContext
from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from app.tools.core import BaseTool

logger = get_logger(__name__)

# 工具类型变量
T = TypeVar('T', bound=BaseTool)


@dataclass
class ToolInfo:
    """工具信息类，存储工具的元数据和类型信息"""
    # 工具类
    tool_class: Type[BaseTool]
    # 工具名称
    name: str
    # 工具描述
    description: str
    # 工具参数类型（可能为None）
    params_class: Optional[Type] = None
    # 错误信息（如果注册过程中发生错误）
    error: Optional[str] = None

    def __post_init__(self):
        """验证创建的工具信息对象"""
        if not self.tool_class:
            raise ValueError("工具类不能为空")
        if not self.name:
            raise ValueError("工具名称不能为空")

    def is_valid(self) -> bool:
        """检查工具信息是否有效"""
        return self.error is None


class ToolFactory:
    """工具工厂

    负责扫描、注册和创建工具实例
    """
    _instance = None  # 单例模式实例

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ToolFactory, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._tools: Dict[str, ToolInfo] = {}  # 工具信息字典：name -> ToolInfo对象
        self._tool_instances: Dict[str, BaseTool] = {}  # 工具实例缓存：name -> instance
        self._initialized = True

    def register_tool(self, tool_class: Type[BaseTool]) -> None:
        """注册工具类

        Args:
            tool_class: 工具类
        """
        if not hasattr(tool_class, '_tool_name'):
            logger.warning(f"工具类 {tool_class.__name__} 未通过@tool装饰器装饰，跳过注册")
            return

        tool_name = tool_class._tool_name

        # 获取参数类
        params_class = getattr(tool_class, 'params_class', None) or getattr(tool_class, '_params_class', None)

        try:
            # 创建工具信息对象
            tool_info = ToolInfo(
                tool_class=tool_class,
                name=tool_name,
                description=tool_class._tool_description,
                params_class=params_class
            )

            # 存储工具信息
            self._tools[tool_name] = tool_info

            # 标记为已注册
            tool_class._registered = True
            logger.debug(f"注册工具: {tool_name}")
        except Exception as e:
            logger.error(f"获取工具 {tool_name} 参数定义时出错: {e}")
            # 请求参数验证失败时，返回详细错误信息
            if hasattr(e, '__str__'):
                logger.error(f"详细错误: {e!s}")
            # 即使有错误也保留一个有效的工具记录，但标记为不可用
            self._tools[tool_name] = ToolInfo(
                tool_class=tool_class,
                name=tool_name,
                description=getattr(tool_class, '_tool_description', "无法获取描述"),
                params_class=None,
                error=str(e)
            )

    def auto_discover_tools(self) -> None:
        """自动发现并注册工具

        扫描app.tools包下的所有模块，查找并注册所有通过@tool装饰的工具类
        """
        # 获取工具包路径
        package_name = 'app.tools'
        tools_entry_points = list(importlib.metadata.entry_points(group='agentlang.tools'))
        package_names = [package_name]
        for entry_point in tools_entry_points:
            package_names.append(entry_point.value)
            logger.info(f"发现工具包: {entry_point.value}")
        try:
            # 定义一个递归扫描函数
            def scan_package(pkg_name: str, pkg_path: str) -> None:
                logger.info(f"扫描包: {pkg_name}")

                # 扫描该包下的所有模块
                for _, module_name, is_pkg in pkgutil.iter_modules([pkg_path]):
                    # 只在 app.tools 包中跳过 core 包
                    if is_pkg and module_name == 'core' and pkg_name == 'app.tools':
                        continue

                    # 如果是子包，递归扫描
                    if is_pkg:
                        subpackage_name = f"{pkg_name}.{module_name}"
                        logger.info(f"发现子包: {subpackage_name}")
                        try:
                            subpackage = importlib.import_module(subpackage_name)
                            # 检查 subpackage.__file__ 是否存在
                            if not hasattr(subpackage, '__file__') or subpackage.__file__ is None:
                                logger.warning(f"子包 {subpackage_name} 没有 __file__ 属性或为 None，跳过扫描")
                                continue

                            subpackage_path = os.path.dirname(subpackage.__file__)

                            # 递归扫描子包
                            scan_package(subpackage_name, subpackage_path)
                        except Exception as e:
                            logger.error(f"扫描子包 {subpackage_name} 失败: {e!s}")
                        continue

                    # 动态导入模块
                    module_fullname = f"{pkg_name}.{module_name}"
                    try:
                        # 导入模块
                        logger.info(f"导入模块: {module_fullname}")
                        module = importlib.import_module(module_fullname)

                        # 查找模块中带有_is_tool标记的类
                        for name, obj in inspect.getmembers(module):
                            if (inspect.isclass(obj) and
                                hasattr(obj, '_is_tool') and
                                obj._is_tool and
                                not getattr(obj, '_registered', False)):
                                # 注册工具类
                                logger.info(f"发现工具类: {name} 在模块 {module_fullname}")
                                self.register_tool(obj)
                    except Exception as e:
                        logger.error(f"加载模块 {module_fullname} 失败: {e!s}")
            for package_name in package_names:
                try:
                    package = importlib.import_module(package_name)
                    package_path = os.path.dirname(package.__file__)
                    # 开始扫描
                    scan_package(package_name, package_path)
                except ImportError:
                    logger.error(f"未找到工具包: {package_name}")
                    continue  # 跳过不存在的包
                except Exception as e:
                    logger.error(f"加载工具包 {package_name} 失败: {e!s}")
                    continue  # 跳过出错的包
        except Exception as e:
            logger.error(f"扫描工具时发生错误: {e!s}", exc_info=True)

    def initialize(self) -> None:
        """初始化工厂，扫描和注册所有工具"""
        self.auto_discover_tools()
        logger.info(f"工具工厂初始化完成，共发现 {len(self._tools)} 个工具")

    def get_tool(self, tool_name: str) -> Optional[ToolInfo]:
        """获取工具信息

        Args:
            tool_name: 工具名称

        Returns:
            Optional[ToolInfo]: 工具信息对象
        """
        if not self._tools:
            self.initialize()

        return self._tools.get(tool_name)

    def get_tool_instance(self, tool_name: str) -> BaseTool:
        """获取工具实例

        Args:
            tool_name: 工具名称

        Returns:
            BaseTool: 工具实例
        """
        # 先检查缓存
        if tool_name in self._tool_instances:
            return self._tool_instances[tool_name]

        # 获取工具信息
        tool_info = self.get_tool(tool_name)
        if not tool_info:
            raise ValueError(f"工具 {tool_name} 不存在")

        # 创建工具实例
        try:
            # 获取类属性
            name = getattr(tool_info.tool_class, 'name', tool_name)
            description = getattr(tool_info.tool_class, 'description', tool_info.description)

            # 显式传递name和description作为实例化参数
            tool_instance = tool_info.tool_class(name=name, description=description)

            # 缓存实例
            self._tool_instances[tool_name] = tool_instance

            return tool_instance
        except Exception as e:
            logger.error(f"创建工具 {tool_name} 实例时出错: {e}")
            raise ValueError(f"无法创建工具 {tool_name} 的实例: {e}")

    def get_all_tools(self) -> Dict[str, ToolInfo]:
        """获取所有工具信息

        Returns:
            Dict[str, ToolInfo]: 工具名称和信息对象的字典
        """
        if not self._tools:
            self.initialize()

        return self._tools

    def get_tool_names(self) -> List[str]:
        """获取所有工具名称

        Returns:
            List[str]: 工具名称列表
        """
        if not self._tools:
            self.initialize()

        return list(self._tools.keys())

    def get_all_tool_instances(self) -> List[BaseTool]:
        """获取所有工具实例

        Returns:
            List[BaseTool]: 工具实例列表
        """
        all_tools = self.get_all_tools()
        return [self.get_tool_instance(tool_name) for tool_name in all_tools.keys()]

    async def run_tool(self, tool_context: ToolContext, tool_name: str, **kwargs) -> ToolResult:
        """运行工具

        Args:
            tool_context: 工具上下文
            tool_name: 工具名称
            **kwargs: 工具参数

        Returns:
            ToolResult: 工具执行结果
        """
        try:
            start_time = time.time()

            # 获取工具实例
            tool_instance = self.get_tool_instance(tool_name)

            # 转换参数类型（如果适用）
            tool_info = self.get_tool(tool_name)
            params_class = tool_info.params_class if tool_info else None
            if params_class:
                try:
                    params = params_class(**kwargs)
                    result = await tool_instance.execute(tool_context, params)
                except Exception as e:
                    logger.error(f"参数验证失败: {e!s}")
                    result = ToolResult(
                        error=f"参数验证失败: {e!s}",
                        name=tool_name
                    )
            else:
                # 向后兼容：不使用参数模型的工具
                result = await tool_instance.execute(tool_context, **kwargs)

            # 设置执行时间
            result.execution_time = time.time() - start_time

            return result
        except Exception as e:
            logger.error(f"执行工具 {tool_name} 失败: {e!s}", exc_info=True)

            # 创建错误结果
            result = ToolResult(
                content="",
                error=f"执行工具失败: {e!s}",
                name=tool_name
            )

            return result


# 创建全局工具工厂实例
tool_factory = ToolFactory()

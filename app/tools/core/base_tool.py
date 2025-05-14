"""工具基类模块

定义所有工具的基础类，提供共同功能和接口
"""

import time
import os
import inspect
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, Optional, Type, TypeVar, Union, ClassVar, get_args, get_origin

from pydantic import ConfigDict, ValidationError

from agentlang.utils.snowflake import Snowflake
from agentlang.context.tool_context import ToolContext
from app.core.entity.message.server_message import ToolDetail
from agentlang.tools.tool_result import ToolResult
from agentlang.logger import get_logger
from app.tools.core.base_tool_params import BaseToolParams

# 定义参数类型变量
T = TypeVar('T', bound=BaseToolParams)


class BaseTool(Generic[T], ABC):
    """工具基类

    所有工具的基类，定义共同接口和功能
    """
    # 工具元数据（类级别）
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    params_class: ClassVar[Type[T]] = None

    # 配置项
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init_subclass__(cls, **kwargs):
        """子类初始化时处理元数据

        在子类定义时自动执行，确定最终的类级别元数据
        """
        super().__init_subclass__(**kwargs)
        logger = get_logger(__name__)

        # 确保子类被标记为未注册
        cls._registered = False

        # ---------- 确定工具名称 (name) ----------
        if cls.__dict__.get('name'):  # 优先级1: 子类直接定义的name属性
            # 保持不变，使用子类定义的值
            pass
        elif hasattr(cls, '_initial_name') and cls._initial_name:  # 优先级2: 装饰器提供的name
            cls.name = cls._initial_name
        else:  # 优先级3: 从文件名自动推断
            try:
                # 获取子类的模块文件路径
                module = inspect.getmodule(cls)
                if module:
                    # 从模块文件路径中提取文件名（不含扩展名）
                    file_path = module.__file__
                    file_name = os.path.basename(file_path)
                    name_without_ext = os.path.splitext(file_name)[0]
                    # 转换为小写
                    generated_name = name_without_ext.lower()
                    logger.debug(f"从文件名 {file_name} 自动生成工具名: {generated_name}")
                    cls.name = generated_name
                else:
                    # 备用方案：从类名生成 (驼峰转下划线)
                    fallback_name = re.sub(r'(?<!^)(?=[A-Z])', '_', cls.__name__).lower()
                    logger.debug(f"无法获取模块文件名，从类名生成工具名: {fallback_name}")
                    cls.name = fallback_name
            except Exception as e:
                logger.warning(f"从文件名生成工具名失败: {e}")
                # 备用方案：使用类名
                cls.name = cls.__name__.lower()

        # ---------- 确定工具描述 (description) ----------
        if cls.__dict__.get('description'):  # 优先级1: 子类直接定义的description
            # 保持不变，使用子类定义的值
            pass
        elif hasattr(cls, '_initial_description') and cls._initial_description:  # 优先级2: 装饰器提供的description
            cls.description = cls._initial_description
        elif cls.__doc__:  # 优先级3: 从类的文档字符串提取
            # 使用inspect.cleandoc处理文档字符串
            cls.description = inspect.cleandoc(cls.__doc__)
        else:
            # 如果都没有，使用默认描述
            cls.description = f"Tool for {cls.name}"
            logger.warning(f"工具 {cls.name} 没有描述信息")

        # ---------- 确定参数类 (params_class) ----------
        if cls.__dict__.get('params_class'):  # 优先级1: 子类直接定义的params_class
            # 保持不变，使用子类定义的值
            pass
        elif hasattr(cls, '__orig_bases__'):  # 优先级2: 从泛型基类(Generic[T])提取参数类型
            for base in cls.__orig_bases__:
                if hasattr(base, '__origin__') and base.__origin__ is Generic:
                    # 检查是否为BaseTool[ParamType]形式
                    continue  # Generic基类不提取

                # 检查是否为像WorkspaceGuardTool[ParamType]这样的特定泛型工具
                if hasattr(base, '__origin__') and hasattr(base, '__args__') and len(base.__args__) > 0:
                    origin = get_origin(base)
                    if origin is not None and issubclass(origin, BaseTool):
                        args = get_args(base)
                        if args and len(args) > 0 and isinstance(args[0], type):
                            cls.params_class = args[0]
                            logger.debug(f"从泛型基类 {base} 提取参数类: {cls.params_class}")
                            break

        if not cls.params_class and hasattr(cls, 'execute'):  # 优先级3: 从execute方法签名提取
            try:
                sig = inspect.signature(cls.execute)
                # 查找第3个参数(跳过self和tool_context)
                params = list(sig.parameters.values())
                if len(params) >= 3:
                    param = params[2]
                    # 检查参数是否有类型注解
                    if param.annotation != inspect.Parameter.empty:
                        cls.params_class = param.annotation
                        logger.debug(f"从execute方法签名提取参数类: {cls.params_class}")
            except Exception as e:
                logger.warning(f"从execute方法签名提取参数类失败: {e}")

        # 更新工厂注册用的内部键
        cls._tool_name = cls.name
        cls._tool_description = cls.description
        cls._params_class = cls.params_class

        # 确保工具被标记为工具
        if not hasattr(cls, '_is_tool'):
            cls._is_tool = True

        logger.debug(f"工具元数据确定: name={cls.name}, params_class={cls.params_class}")

    def __init__(self, **data):
        """初始化工具"""
        # 保存实例级别的覆盖值
        self._custom_name = data.get('name', None)
        self._custom_description = data.get('description', None)

        # 设置其他实例属性（跳过name和description）
        for key, value in data.items():
            if key not in ['name', 'description']:
                setattr(self, key, value)

    @abstractmethod
    async def execute(self, tool_context: ToolContext, params: T) -> ToolResult:
        """执行工具

        Args:
            tool_context: 工具上下文
            params: 工具参数

        Returns:
            ToolResult: 工具执行结果
        """
        pass

    def get_effective_name(self) -> str:
        """获取最终生效的工具名称

        优先级：实例自定义名称 > 类名称

        Returns:
            str: 工具名称
        """
        return self._custom_name if self._custom_name is not None else self.__class__.name

    def get_effective_description(self) -> str:
        """获取最终生效的工具描述

        优先级：实例自定义描述 > 类描述

        Returns:
            str: 工具描述
        """
        return self._custom_description if self._custom_description is not None else self.__class__.description

    async def __call__(self, tool_context: ToolContext, **kwargs) -> ToolResult:
        """执行工具

        这是工具调用的主要入口点，支持通过参数字典调用工具

        此方法会自动完成以下工作：
        1. 参数验证和转换：将传入的字典参数转换为工具需要的Pydantic模型
        2. 性能计时：记录工具执行时间
        3. 结果处理：确保结果包含必要字段
        4. 错误处理：通过自定义错误消息机制提供更友好的错误提示

        Args:
            tool_context: 工具上下文
            **kwargs: 参数字典

        Returns:
            ToolResult: 工具执行结果
        """
        start_time = time.time()

        logger = get_logger(__name__)

        # 没有参数模型类型的工具是无效的
        if not self.params_class:
            error_msg = f"工具 {self.get_effective_name()} 没有定义参数模型类型"
            logger.error(error_msg)
            return ToolResult(
                error=error_msg,
                name=str(self.get_effective_name())
            )

        # 尝试根据参数字典创建参数模型实例
        try:
            params = self.params_class(**kwargs)
        except ValidationError as e:
            # 参数验证失败处理
            error_details = e.errors()
            logger.debug(f"验证错误详情: {error_details}")

            # 检查是否有自定义错误消息
            # 此处实现了错误回调机制，允许工具参数类为特定字段和错误类型提供自定义错误消息
            for err in error_details:
                if err.get("loc"):
                    field_name = err.get("loc")[0]
                    error_type = err.get("type")

                    # 调用参数类的自定义错误消息方法
                    custom_error = self.params_class.get_custom_error_message(field_name, error_type)
                    if custom_error:
                        logger.info(f"使用自定义错误消息: field={field_name}, type={error_type}")
                        return ToolResult(
                            error=custom_error,
                            name=str(self.get_effective_name())
                        )

            # 如果没有自定义错误消息，使用友好的错误处理逻辑
            # 判断错误类型并生成相应的友好错误消息
            pretty_error_msg = self._generate_friendly_validation_error(error_details, str(self.get_effective_name()))
            return ToolResult(
                error=pretty_error_msg,
                name=str(self.get_effective_name())
            )
        except Exception as e:
            # 其他类型的异常
            logger.error(f"参数验证失败: {e!s}")
            pretty_error = f"工具 '{self.get_effective_name()}' 的参数验证失败，请检查输入参数的格式是否正确"
            result = ToolResult(
                error=pretty_error,
                name=str(self.get_effective_name())
            )
            return result

        # 执行工具
        try:
            result = await self.execute(tool_context, params)
        except Exception as e:
            logger.error(f"工具 {self.get_effective_name()} 执行出错: {e}", exc_info=True)
            # 捕获执行错误并返回错误结果
            result = ToolResult(
                error=f"工具执行失败: {e!s}",
                name=str(self.get_effective_name())
            )

        # 设置执行时间和名称
        execution_time = time.time() - start_time
        result.execution_time = execution_time
        result.name = str(self.get_effective_name())

        # 设置解释说明（如果有）
        explanation = params.explanation if hasattr(params, 'explanation') else None
        if explanation:
            result.explanation = explanation

        return result

    def _generate_friendly_validation_error(self, error_details, tool_name: str) -> str:
        """生成友好的验证错误消息

        Args:
            error_details: pydantic验证错误详情
            tool_name: 工具名称

        Returns:
            str: 友好的错误消息
        """
        logger = get_logger(__name__)

        # 检查是否有必填字段缺失的错误
        missing_fields = []
        type_errors = []
        other_errors = []

        for err in error_details:
            err_type = err.get("type", "")
            field_path = ".".join(str(loc) for loc in err.get("loc", []))

            if err_type == "missing":
                missing_fields.append(field_path)
            elif "type" in err_type:  # 类型错误，如type_error
                # 获取预期类型
                expected_type = "有效值"
                if "expected_type" in err.get("ctx", {}):
                    expected_type = err["ctx"]["expected_type"]
                elif "expected" in err.get("ctx", {}):
                    expected_type = err["ctx"]["expected"]

                # 获取实际值的类型
                received_type = "无效类型"
                if "input_type" in err.get("ctx", {}):
                    received_type = err["ctx"]["input_type"]
                elif "received" in err.get("ctx", {}):
                    received_type = str(type(err["ctx"]["received"]).__name__)

                error_msg = f"参数 '{field_path}' 应为 {expected_type} 类型，而不是 {received_type}"
                type_errors.append(error_msg)
            else:
                # 其他类型的错误
                msg = err.get("msg", "未知错误")
                other_errors.append(f"参数 '{field_path}': {msg}")

        # 构建友好的错误消息
        pretty_msg_parts = []

        if missing_fields:
            fields_str = "、".join(missing_fields)
            pretty_msg_parts.append(f"缺少必填参数：{fields_str}")

        if type_errors:
            pretty_msg_parts.append("类型错误：" + "；".join(type_errors))

        if other_errors:
            pretty_msg_parts.append("验证错误：" + "；".join(other_errors))

        if not pretty_msg_parts:
            # 如果没有解析出具体错误，提供一个通用的错误消息
            return f"工具 '{tool_name}' 的参数验证失败，请检查输入格式是否正确"

        return "工具调用失败！" + "；".join(pretty_msg_parts) + "，请确保参数传递正确，检查是否为语法正确的 JSON 对象，同时也有可能是输出的内容超出长度限制导致，请减少单次要输出的内容。"

    def to_param(self) -> Dict:
        """转换工具为函数调用格式

        Returns:
            Dict: 函数调用格式的工具描述
        """
        logger = get_logger(__name__)

        # 注意：移除了这里的 "additionalProperties": False
        parameters = {
            "type": "object",
            "properties": {},
            "required": [],
        }

        if self.params_class:
            try:
                # 使用 params_class 的清理方法生成 schema
                schema = self.params_class.model_json_schema_clean()

                # 只需要 properties 和 required
                if 'properties' in schema:
                    parameters['properties'] = schema['properties']

                if 'required' in schema:
                    parameters['required'] = schema['required']
                else:
                    # 如果原始 schema 没有 required，则默认所有非 Optional 字段为必填
                    if 'properties' in parameters:
                         parameters['required'] = list(parameters['properties'].keys())

                # 确保 explanation 字段必填 (如果存在且非 Optional)
                if 'explanation' in parameters.get('properties', {}) and 'explanation' not in parameters['required']:
                     is_optional = False
                     explanation_field = self.params_class.model_fields.get('explanation')
                     if explanation_field and getattr(explanation_field, 'annotation', None):
                         from typing import get_args, get_origin
                         origin = get_origin(explanation_field.annotation)
                         if origin is Union:
                             args = get_args(explanation_field.annotation)
                             if type(None) in args:
                                 is_optional = True
                         # Handle Optional[T] syntax introduced in Python 3.10
                         elif origin is Optional:
                            is_optional = True

                     if not is_optional:
                        # 只有在 properties 中确实存在 explanation 时才添加
                        if 'explanation' in parameters.get('properties', {}):
                           parameters['required'].append('explanation')

            except Exception as e:
                logger.error(f"生成工具参数模式时出错: {e!s}", exc_info=True)

        # 如果清理后 properties 为空，也移除它
        if not parameters['properties']:
            parameters.pop('properties')
            # 如果 properties 为空，required 也应该为空
            parameters.pop('required', None)

        # 获取最终生效的工具名称和描述
        effective_name = self.get_effective_name()
        effective_description = self.get_effective_description()

        # 确保是字符串
        if not isinstance(effective_name, str):
            effective_name = str(effective_name)
        if not isinstance(effective_description, str):
            effective_description = str(effective_description)

        return {
            "type": "function",
            "function": {
                "name": effective_name,
                "description": effective_description,
                "parameters": parameters,
            },
        }

    def generate_message_id(self) -> str:
        """生成消息ID

        使用默认方式生成
        """
        # 使用雪花算法生成ID
        snowflake = Snowflake.create_default()
        return str(snowflake.get_id())

    def get_prompt_hint(self) -> str:
        """
        获取工具想要附加到主 Prompt 的提示信息。

        子类可以覆盖此方法以提供特定于工具的上下文或指令，
        这些信息将在 Agent 初始化时被追加到基础 Prompt 中。

        Returns:
            str: 要追加到 Prompt 的提示字符串，默认为空。
        """
        return ""

    async def get_tool_detail(self, tool_context: ToolContext, result: ToolResult, arguments: Dict[str, Any] = None) -> Optional[ToolDetail]:
        """
        根据工具执行结果获取对应的ToolDetail

        每个工具类可以重写此方法，提供适合该工具的ToolDetail
        可以返回None表示没有需要展示的工具详情

        Args:
            tool_context: 工具上下文
            result: 工具执行的结果
            arguments: 其他额外参数字典，用于构建特定类型的详情

        Returns:
            Optional[ToolDetail]: 工具详情对象，可能为None
        """
        # 默认实现：返回None
        return None

    async def get_before_tool_call_friendly_content(self, tool_context: ToolContext, arguments: Dict[str, Any] = None) -> str:
        """获取工具调用前的友好内容"""
        return arguments["explanation"]

    async def get_after_tool_call_friendly_content(self, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> str:
        """
        获取工具调用后的友好内容

        Args:
            tool_context: 工具上下文
            result: 工具执行结果
            execution_time: 执行耗时
            arguments: 执行参数

        Returns:
            str: 友好的执行结果消息
        """
        return ""

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """
        获取工具调用后的友好动作和备注

        Args:
            tool_name: 工具名称
            tool_context: 工具上下文
            result: 工具执行结果
            execution_time: 执行耗时
            arguments: 执行参数

        Returns:
            Dict: 包含action和remark的字典
        """
        return {
            "action": "",
            "remark": ""
        }

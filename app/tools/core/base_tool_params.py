"""工具参数基类模块

定义所有工具参数模型的基类，提供通用参数字段
"""

import inspect
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class BaseToolParams(BaseModel):
    """工具参数基类

    所有工具参数模型的基类，定义共同参数
    """
    # TODO： 重复率太高，浪费 token
    explanation: str = Field(
        "", # 虽然有默认值，但在实际调用时会被处理为必填字段，以确保大模型始终提供解释，但如果大模型小概率出现没给，也不会报错
        description="""
        请以第一人称（使用"我"）解释接下来你将要使用这个工具做什么 - 简要说明你的目的、预期结果，以及你将如何使用结果来帮助用户。
        **在与用户沟通时切勿提及工具名称。** 例如，说"我将编辑你的文件"而不是"我需要使用 write_to_file 工具来编辑你的文件"
        """
    )

    @classmethod
    def get_custom_error_message(cls, field_name: str, error_type: str) -> Optional[str]:
        """获取自定义参数错误信息

        此方法允许工具参数类为特定字段和错误类型提供自定义错误消息。
        子类可以覆盖此方法，为常见错误场景提供更友好、更具有指导性的错误信息。

        Args:
            field_name: 参数字段名称
            error_type: 错误类型，来自Pydantic验证错误

        Returns:
            Optional[str]: 自定义错误信息，None表示使用默认错误信息
        """
        return None

    @classmethod
    def model_json_schema_clean(cls, **kwargs) -> Dict:
        """生成清理过的JSON Schema

        基于Pydantic的model_json_schema，但会移除一些不必要的字段

        Returns:
            Dict: 清理后的JSON Schema
        """
        schema = cls.model_json_schema(**kwargs)
        # 清理schema
        if 'properties' in schema:
            cls._clean_schema_properties(schema['properties'])
            cls._remove_title_recursive(schema)
            cls._clean_description_fields(schema['properties'])
        return schema

    @classmethod
    def _clean_schema_properties(cls, properties: Dict[str, Any]):
        """递归清理Pydantic生成的schema properties

        移除default、additionalProperties等不必要的字段

        Args:
            properties: 属性字典
        """
        if not isinstance(properties, dict):
            return

        for prop_name, prop_schema in list(properties.items()):
            if not isinstance(prop_schema, dict):
                continue


            # 只有 explanation 字段需要移除 default
            if prop_name == 'explanation':
                prop_schema.pop('default', None)
            # 移除不必要的字段
            prop_schema.pop('additionalProperties', None)

            # 递归处理嵌套的properties
            if 'properties' in prop_schema:
                cls._clean_schema_properties(prop_schema['properties'])

            # 递归处理嵌套的items (用于数组)
            if 'items' in prop_schema and isinstance(prop_schema['items'], dict):
                prop_schema['items'].pop('additionalProperties', None)

                if 'properties' in prop_schema['items']:
                    cls._clean_schema_properties(prop_schema['items']['properties'])

                if 'items' in prop_schema['items']:
                    cls._clean_schema_properties(prop_schema['items'])

    @classmethod
    def _remove_title_recursive(cls, schema_obj: Any):
        """递归移除schema对象中的title字段

        Args:
            schema_obj: Schema对象，可能是字典或列表
        """
        if isinstance(schema_obj, dict):
            schema_obj.pop('title', None)  # 移除当前字典的title
            for key, value in schema_obj.items():
                cls._remove_title_recursive(value)  # 递归处理值
        elif isinstance(schema_obj, list):
            for item in schema_obj:
                cls._remove_title_recursive(item)  # 递归处理列表项

    @classmethod
    def _clean_description_fields(cls, properties: Dict[str, Any]):
        """清理所有属性的description字段，移除多余的空格和换行符

        Args:
            properties: 属性字典
        """
        if not isinstance(properties, dict):
            return

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue

            # 清理当前属性的description
            if 'description' in prop_schema:
                # 使用inspect.cleandoc清理文档字符串
                if isinstance(prop_schema['description'], str):
                    prop_schema['description'] = inspect.cleandoc(prop_schema['description']).strip()

            # 递归处理嵌套的properties
            if 'properties' in prop_schema and isinstance(prop_schema['properties'], dict):
                cls._clean_description_fields(prop_schema['properties'])

            # 递归处理数组项的properties
            if 'items' in prop_schema and isinstance(prop_schema['items'], dict):
                if 'description' in prop_schema['items']:
                    if isinstance(prop_schema['items']['description'], str):
                        prop_schema['items']['description'] = inspect.cleandoc(prop_schema['items']['description']).strip()

                if 'properties' in prop_schema['items'] and isinstance(prop_schema['items']['properties'], dict):
                    cls._clean_description_fields(prop_schema['items']['properties'])

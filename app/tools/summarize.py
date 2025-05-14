from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from agentlang.llms.factory import LLMFactory
from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from agentlang.utils.token_estimator import truncate_text_by_token
from app.core.entity.message.server_message import DisplayType, FileContent, ToolDetail
from app.tools.core import BaseTool, BaseToolParams, tool
from app.tools.read_file import ReadFile, ReadFileParams

logger = get_logger(__name__)

# 默认最大 Token 数
DEFAULT_MAX_TOKENS = 10000


class SummarizeParams(BaseToolParams):
    """摘要工具参数"""
    file_path: str = Field(
        ...,
        description="需要生成摘要的文件路径"
    )
    max_length: int = Field(
        default=300,
        description="摘要的最大长度（字符数）"
    )


@tool()
class Summarize(BaseTool[SummarizeParams]):
    """
    摘要工具，用于从文本文件内容生成简洁的摘要。

    适用于包括但不限于以下场景：
    - 长篇文章的内容概括
    - 研究论文的摘要生成
    - 会议记录的要点提取
    - 新闻文章的核心信息提取

    要求：
    - 摘要应基于文件内容，不要添加不在原文中的信息
    - 摘要应保留原文的关键信息和主要观点

    调用示例：
    ```
    {
        "file_path": "./webview_report/article.md",
        "max_length": 300
    }
    ```
    """

    async def execute(
        self,
        tool_context: ToolContext,
        params: SummarizeParams
    ) -> ToolResult:
        return await self.execute_purely(params)

    async def execute_purely(
        self,
        params: SummarizeParams
    ) -> ToolResult:
        """执行摘要并返回结果。

        Args:
            tool_context: 工具上下文
            params: 摘要参数对象

        Returns:
            ToolResult: 包含摘要结果的工具结果
        """
        try:
            # 获取参数
            file_path = params.file_path
            max_length = params.max_length
            model_id = "deepseek-chat"

            # 记录摘要请求
            logger.info(f"执行摘要: 文件路径={file_path}, 最大长度={max_length}, 模型={model_id}")

            # 读取文件内容
            file_content = await self._read_file(file_path)
            if not file_content:
                return ToolResult(error=f"无法读取文件: {file_path}")

            # 提取文件名用于显示
            file_name = file_path.split('/')[-1]

            # 调用内部方法处理摘要
            summary_content = await self.summarize_content(
                content=file_content,
                title=file_name,
                max_length=max_length,
                model_id=model_id
            )

            if not summary_content:
                return ToolResult(error="生成摘要失败")

            # 创建结果
            result = ToolResult(
                content=f"## 文件摘要: {file_name}\n\n{summary_content}",
                extra_info={"file_path": file_path, "file_name": file_name}
            )

            return result

        except Exception as e:
            logger.exception(f"摘要操作失败: {e!s}")
            return ToolResult(error=f"摘要操作失败: {e!s}")

    async def summarize_content(
        self,
        content: str,
        title: str = "文档",
        max_length: int = 300,
        model_id: str = "deepseek-chat"
    ) -> Optional[str]:
        """直接对文本内容生成摘要，无需文件读取

        Args:
            tool_context: 工具上下文
            content: 需要摘要的文本内容
            title: 内容标题
            max_length: 摘要最大长度
            temperature: 模型温度
            model_id: 使用的模型ID

        Returns:
            Optional[str]: 摘要内容，失败则返回None
        """
        try:
            # 在这里进行截断
            truncated_content, is_truncated = truncate_text_by_token(content, DEFAULT_MAX_TOKENS)
            if is_truncated:
                logger.warning(f"摘要内容被截断: title='{title}', original_length={len(content)}, truncated_length={len(truncated_content)}")

            # 获取并格式化当前时间上下文
            current_time_str = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S 星期{}(第%W周)".format(
                ["一", "二", "三", "四", "五", "六", "日"][datetime.now().weekday()]))

            # 构建提示语
            prompt = f"""请为以下文本内容生成一个简洁明了的摘要，控制在 {max_length} 字符以内。
摘要应包含文档的主要观点、关键信息和重要结论。
请确保摘要是对原始内容的忠实概括，不要添加原文中不存在的信息。

当前时间: {current_time_str}

文档标题: {title}

文本内容:
```
{truncated_content}
```

请提供摘要:"""

            # 构建消息
            messages = [
                {
                    "role": "system",
                    "content": "你是一个专业的文本摘要助手，擅长提取文本的核心内容并生成简洁明了的摘要。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]

            # 请求模型
            response = await LLMFactory.call_with_tool_support(
                model_id=model_id,
                messages=messages,
                tools=None,  # 不需要工具支持
                stop=None,
            )

            # 处理响应
            if not response or not response.choices or len(response.choices) == 0:
                logger.error("没有从模型收到有效响应")
                return None

            # 获取摘要内容
            summary_content = response.choices[0].message.content

            # 如果内容被截断，添加提示
            if is_truncated:
                summary_content += "\n\n(注：此摘要基于截断内容生成)"

            return summary_content if summary_content else None

        except Exception as e:
            logger.exception(f"处理内容摘要失败: {e!s}")
            return None

    async def get_tool_detail(self, tool_context: ToolContext, result: ToolResult, arguments: Dict[str, Any] = None) -> Optional[ToolDetail]:
        """
        生成工具详情，用于前端展示

        Args:
            tool_context: 工具上下文
            result: 工具结果
            arguments: 工具参数

        Returns:
            Optional[ToolDetail]: 工具详情
        """
        if not result.content:
            return None

        try:
            file_name = result.extra_info.get("file_name", "文件") if result.extra_info else "文件"

            # 返回Markdown格式的摘要内容
            return ToolDetail(
                type=DisplayType.MD,
                data=FileContent(
                    file_name=f"{file_name}_摘要.md",
                    content=result.content
                )
            )
        except Exception as e:
            logger.error(f"生成工具详情失败: {e!s}")
            return None

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """获取工具调用后的友好动作和备注"""
        if not arguments or "file_path" not in arguments:
            return {
                "action": "生成摘要",
                "remark": "已完成摘要生成"
            }

        file_path = arguments["file_path"]
        # 提取文件名
        file_name = file_path.split('/')[-1]
        return {
            "action": "生成摘要",
            "remark": f"已为 {file_name} 生成摘要"
        }

    async def _read_file(self, file_path: str) -> Optional[str]:
        """读取文件内容

        Args:
            tool_context: 工具上下文
            file_path: 文件路径

        Returns:
            Optional[str]: 文件内容，如果读取失败则返回None
        """
        try:
            read_file_tool = ReadFile()
            read_file_params = ReadFileParams(
                file_path=file_path,
                should_read_entire_file=True
            )

            result = await read_file_tool.execute_purely(read_file_params)

            if result.ok:
                return result.content
            else:
                logger.error(f"读取文件 {file_path} 失败: {result.content}")
                return None
        except Exception as e:
            logger.error(f"读取文件 {file_path} 时发生异常: {e}")
            return None

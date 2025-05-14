import base64
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from agentlang.llms.factory import LLMFactory
from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from app.core.entity.message.server_message import DisplayType, FileContent, ToolDetail
from app.tools.core import BaseTool, BaseToolParams, tool

logger = get_logger(__name__)


class VisualUnderstandingParams(BaseToolParams):
    """视觉理解工具参数"""
    images: List[str] = Field(
        ...,
        description="图片来源列表，可以是图片URL或本地文件路径，支持多图片输入"
    )
    query: str = Field(
        ...,
        description="关于图片的问题或要求"
    )


@tool()
class VisualUnderstanding(BaseTool[VisualUnderstandingParams]):
    """
    视觉理解工具，用于分析和解释图像内容。

    适用于包括但不限于以下场景：
    - 图片内容识别与描述
    - 图表分析与解读
    - 视觉场景理解与解释
    - 图像中文字识别与提取
    - 多图片对比分析

    要求：
    - 输入图片路径或URL链接，支持同时输入多张图片
    - 提供对图片内容的具体问题或要求描述

    调用示例：
    ```
    {
        "images": ["https://example.com/image1.jpg", "https://example.com/image2.jpg"],
        "query": "这些图片里有什么相同点和不同点？请详细描述。"
    }
    ```

    或
    ```
    {
        "images": ["./webview_reports/image1.jpg", "./webview_reports/image2.jpg"],
        "query": "识别这些图片中的文字内容并进行对比。"
    }
    ```
    """

    async def execute(
        self,
        tool_context: ToolContext,
        params: VisualUnderstandingParams
    ) -> ToolResult:
        """执行视觉理解并返回结果。

        Args:
            tool_context: 工具上下文
            params: 视觉理解参数对象

        Returns:
            ToolResult: 包含视觉理解结果的工具结果
        """
        return await self.execute_purely(params)

    async def execute_purely(
        self,
        params: VisualUnderstandingParams
    ) -> ToolResult:
        """执行视觉理解并返回结果。

        Args:
            params: 视觉理解参数对象

        Returns:
            ToolResult: 包含视觉理解结果的工具结果
        """
        try:
            # 获取参数
            images = params.images
            query = params.query
            # 固定值，未来可能会重新放到参数里
            model_id = "doubao-1.5-vision-pro-32k"

            # 记录视觉理解请求
            logger.info(f"执行视觉理解: 图片数量={len(images)}, 查询={query}, 模型={model_id}")

            # 处理所有图片来源
            image_data_list = []
            for image_source in images:
                image_data = await self._process_image_source(image_source)
                if not image_data:
                    return ToolResult(error=f"无法处理图片来源: {image_source}")
                image_data_list.append(image_data)

            # 获取并格式化当前时间上下文
            current_time_str = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S 星期{}(第%W周)".format(
                ["一", "二", "三", "四", "五", "六", "日"][datetime.now().weekday()]))

            # 构建消息内容
            content = [
                {
                    "type": "text",
                    "text": query
                }
            ]

            # 添加所有图片
            for i, image_data in enumerate(image_data_list):
                if i > 0:
                    content.append({
                        "type": "text",
                        "text": f"图片 {i+1}:"
                    })
                content.append({
                    "type": "image_url",
                    "image_url": image_data
                })

            # 构建消息
            messages = [
                {
                    "role": "system",
                    "content": "你是一个专业的视觉理解助手，擅长分析和解释图像内容。当前时间：" + current_time_str
                },
                {
                    "role": "user",
                    "content": content
                }
            ]

            # 请求模型
            response = await LLMFactory.call_with_tool_support(
                model_id=model_id,
                messages=messages,
                tools=None,  # 不需要工具支持
                stop=None
            )

            # 处理响应
            if not response or not response.choices or len(response.choices) == 0:
                return ToolResult(error="没有从模型收到有效响应")

            # 获取视觉理解内容
            content = response.choices[0].message.content

            # 提取图像来源的描述性信息用于展示
            image_source_names = [self._extract_image_source_name(image) for image in images]

            # 创建结果
            result = ToolResult(
                content=content,
                extra_info={
                    "images": images,
                    "image_source_names": image_source_names,
                    "image_count": len(images)
                }
            )

            return result

        except Exception as e:
            logger.exception(f"视觉理解操作失败: {e!s}")
            return ToolResult(error=f"视觉理解操作失败: {e!s}")

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
            image_count = result.extra_info.get("image_count", 0) if result.extra_info else 0

            title = "图片视觉理解"
            if image_count == 1:
                image_source_name = result.extra_info.get("image_source_names", ["图片"])[0] if result.extra_info else "图片"
                title = f"图片视觉理解: {image_source_name}"
            elif image_count > 1:
                title = f"多图片视觉理解 ({image_count}张)"

            # 返回Markdown格式的视觉理解内容
            return ToolDetail(
                type=DisplayType.MD,
                data=FileContent(
                    file_name="视觉理解结果.md",
                    content=f"## {title}\n\n{result.content}"
                )
            )
        except Exception as e:
            logger.error(f"生成工具详情失败: {e!s}")
            return None

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """获取工具调用后的友好动作和备注"""
        if not arguments or "images" not in arguments:
            return {
                "action": "视觉理解",
                "remark": "已完成图片理解"
            }

        images = arguments["images"]
        image_count = len(images) if isinstance(images, list) else 1

        if image_count == 1:
            image_source_name = self._extract_image_source_name(images[0])
            return {
                "action": "视觉理解",
                "remark": f"已理解图片: {image_source_name}"
            }
        else:
            return {
                "action": "视觉理解",
                "remark": f"已理解 {image_count} 张图片"
            }

    async def _process_image_source(self, image_source: str) -> Optional[Dict[str, str]]:
        """处理单个图片来源，转换为模型可接受的格式

        Args:
            image_source: 图片URL或本地文件路径

        Returns:
            Optional[Dict[str, str]]: 处理后的图片数据，格式为{"url": url_or_base64}
        """
        try:
            # 判断是否为URL
            if re.match(r'^https?://', image_source):
                # 如果是URL，直接返回
                return {"url": image_source}
            else:
                # 如果是本地文件路径，转换为base64
                return {"url": self._local_file_to_base64(image_source)}
        except Exception as e:
            logger.error(f"处理图片来源失败: {e!s}")
            return None

    def _local_file_to_base64(self, file_path: str) -> str:
        """将本地文件转换为base64编码

        Args:
            file_path: 本地文件路径

        Returns:
            str: base64编码后的图片数据，包含mime类型前缀
        """
        # 确保文件路径是绝对路径
        if not os.path.isabs(file_path):
            file_path = os.path.abspath(file_path)

        # 获取文件扩展名
        file_ext = Path(file_path).suffix.lower().lstrip('.')
        # 映射文件扩展名到MIME类型
        mime_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'bmp': 'image/bmp',
        }
        mime_type = mime_types.get(file_ext, 'image/jpeg')

        # 读取文件并转换为base64
        with open(file_path, "rb") as image_file:
            base64_data = base64.b64encode(image_file.read()).decode('utf-8')

        # 返回带有mime类型前缀的base64数据
        return f"data:{mime_type};base64,{base64_data}"

    def _extract_image_source_name(self, image_source: str) -> str:
        """从图片来源提取显示名称

        Args:
            image_source: 图片URL或本地文件路径

        Returns:
            str: 图片显示名称
        """
        if re.match(r'^https?://', image_source):
            # 如果是URL，提取URL中的文件名
            file_name = image_source.split('/')[-1].split('?')[0]
            return file_name if file_name else "网络图片"
        else:
            # 如果是本地文件路径，提取文件名
            return os.path.basename(image_source)

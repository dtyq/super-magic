"""
思考工具模块

提供基于Chain-of-Thought(CoT)的深度思考和规划功能，帮助代理进行推理和决策。
"""

from typing import Any, Dict, List

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from agentlang.tools.tool_result import ToolResult
from app.tools.core import BaseTool, BaseToolParams, tool


class ThinkingParams(BaseToolParams):
    """思考工具参数模型"""
    problem: str = Field(
        ...,
        description="需要思考的问题或挑战，应明确表述核心疑问"
    )
    thinking: str = Field(
        ...,
        description="对问题的思考过程和分析，包括背景、上下文、观察以及思考的推理过程"
    )
    steps: List[Dict[str, str]] = Field(
        default=[],
        description="思考的步骤列表，每个步骤包含标题和详细的推理过程"
    )
    target: str = Field(
        default="",
        description="思考的目标结果，如结论、解决方案、行动计划或决策建议"
    )


@tool()
class Thinking(BaseTool[ThinkingParams]):
    """思考工具，用于基于提供的上下文进行深度推理和规划

通过Chain-of-Thought(CoT)方法进行深度思考和分析。

使用此工具可以系统地分析复杂问题、制定计划或评估方案。工具接收您的深度思考过程，并将其结构化呈现。

当面对复杂问题时，请:
1. 明确定义问题和思考目标
2. 拆分为多个子问题或思考步骤
3. 逐步推理，每步都展示详细的推理过程和清晰的中间结论
4. 考虑多个视角、假设和约束条件
5. 评估各种可能性和潜在影响
6. 整合所有步骤的结论，形成最终建议

适用场景：复杂决策分析、项目规划、问题根因分析、风险评估、方案比较等。
    """

    async def execute(self, tool_context: ToolContext, params: ThinkingParams) -> ToolResult:
        """
        执行思考过程并返回结果

        Args:
            tool_context: 工具上下文
            params: 思考工具参数

        Returns:
            ToolResult: 包含思考过程和结论的工具结果
        """
        # 构建格式化输出
        output = []

        # 添加问题和思考过程
        output.append(f"关于{params.problem}，{params.thinking}")

        # 添加流程
        output.append("流程：\n")
        for i, step in enumerate(params.steps, 1):
            title = step.get("title", f"步骤 {i}")
            content = step.get("content", "")
            output.append(f"第{i}步: {title}\n{content}\n")

        # 添加目标结果
        output.append(f"所以，{params.target}")

        # 返回结果
        return ToolResult(
            name=self.name,
            content="\n".join(output),
        )

    async def get_before_tool_call_friendly_content(self, tool_context: ToolContext, arguments: Dict[str, Any] = None) -> str:
        """
        获取工具调用前的友好内容
        """
        problem = arguments.get("problem", "") if arguments else ""
        thinking = arguments.get("thinking", "") if arguments else ""

        if problem and thinking:
            return f"开始深入思考问题：{problem}，{thinking}"
        elif problem:
            return f"开始深入思考问题：{problem}"
        else:
            return arguments["explanation"]

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
        problem = ""
        if arguments and "problem" in arguments:
            problem = arguments["problem"]
            # 截断过长的问题描述
            if len(problem) > 100:
                problem = problem[:100] + "..."

        return {
            "action": "深度思考分析",
            "remark": problem
        }

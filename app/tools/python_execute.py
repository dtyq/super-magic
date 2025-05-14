import asyncio
import json
import os
from typing import Any, Dict, Optional

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from app.core.entity.message.server_message import DisplayType, FileContent, ScriptExecutionContent, ToolDetail
from agentlang.tools.tool_result import ToolResult
from agentlang.logger import get_logger
from app.tools.core import BaseToolParams, tool
from app.tools.workspace_guard_tool import WorkspaceGuardTool

logger = get_logger(__name__)


class PythonExecuteParams(BaseToolParams):
    """Python代码执行参数

    注意：code 和 file_path 参数只能二选一，不能同时提供，也不能同时为空：
    - 当提供 code 参数时，将执行代码字符串
    - 当提供 file_path 参数时，将执行指定路径的Python文件
    """
    code: Optional[str] = Field(
        None,
        description="要执行的Python代码字符串，与file_path二选一，不能同时提供"
    )
    file_path: Optional[str] = Field(
        None,
        description="要执行的Python文件路径，与code二选一，不能同时提供"
    )
    cwd: Optional[str] = Field(
        None,
        description="命令执行的工作目录（可选）"
    )
    timeout: int = Field(
        60,
        description="执行超时时间（秒），默认60秒"
    )
    args: Optional[str] = Field(
        None,
        description="传递给Python脚本的命令行参数（可选）"
    )


@tool()
class PythonExecute(WorkspaceGuardTool[PythonExecuteParams]):
    """
    执行Python代码的工具，支持代码字符串和文件路径执行

    使用场景：
    - 执行Python代码字符串
    - 执行Python脚本文件
    - 进行数据处理
    - 测试功能实现

    注意：
    - code 和 file_path 参数只能二选一，不能同时提供
    - 代码将在新的Python解释器进程中执行
    - 支持设置工作目录
    - 可以设置超时时间
    - 可以向脚本传递命令行参数
    """

    async def execute(
        self,
        tool_context: ToolContext,
        params: PythonExecuteParams
    ) -> ToolResult:
        """
        执行提供的Python代码或脚本文件，带有超时限制。

        Args:
            tool_context: 工具上下文
            params: 参数对象，包含要执行的代码或文件路径和超时设置

        Returns:
            ToolResult: 包含执行输出或错误信息。
        """
        # 验证参数
        if not params.code and not params.file_path:
            return ToolResult(error="参数错误：必须提供code或file_path参数之一")

        if params.code and params.file_path:
            return ToolResult(error="参数错误：code和file_path参数不能同时提供，请只选择一种方式执行Python代码")

        try:
            # 处理工作目录
            work_dir = self.base_dir
            if params.cwd:
                # 使用父类方法获取安全的工作目录路径
                cwd_path, error = self.get_safe_path(params.cwd)
                if error:
                    return ToolResult(error=f"工作目录错误：{error}")
                work_dir = cwd_path

            # 确保工作目录存在
            if not work_dir.exists():
                return ToolResult(
                    error=f"工作目录错误：目录不存在 - {work_dir}"
                )

            # 根据参数类型准备执行命令
            if params.file_path:
                # 验证文件路径安全性
                file_path, error = self.get_safe_path(params.file_path)
                if error:
                    return ToolResult(error=f"文件路径错误：{error}")

                # 确保文件存在
                if not file_path.exists():
                    return ToolResult(
                        error=f"文件错误：Python文件不存在 - {file_path}"
                    )

                # 构建命令：python file_path [args]
                cmd_args = ["python", str(file_path)]
                if params.args:
                    cmd_args.extend(params.args.split())

                logger.debug(f"执行Python文件: {file_path}, 工作目录: {work_dir}")

            else:
                # 执行代码字符串
                # 创建临时Python文件
                temp_file = work_dir / "_temp_code.py"
                try:
                    with open(temp_file, "w", encoding="utf-8") as f:
                        f.write(params.code)

                    # 构建命令：python _temp_code.py [args]
                    cmd_args = ["python", str(temp_file)]
                    if params.args:
                        cmd_args.extend(params.args.split())

                    logger.debug(f"执行Python代码字符串, 工作目录: {work_dir}")

                except Exception as e:
                    logger.error(f"创建临时Python文件失败: {e}")
                    return ToolResult(
                        error=f"临时文件错误：无法创建临时Python文件 - {e}"
                    )

            # 创建进程
            try:
                env_vars = {
                    **os.environ,
                    'PYTHONIOENCODING': 'utf-8',
                    'MPLCONFIGDIR': '/root/.config/matplotlib',
                    'LC_ALL': 'C.UTF-8',
                    'LANG': 'C.UTF-8'
                }

                process = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(work_dir),
                    env=env_vars,
                )

                # 等待进程完成，带超时
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=params.timeout
                )
                stdout_str = stdout.decode(errors='replace').strip() if stdout else ""
                stderr_str = stderr.decode(errors='replace').strip() if stderr else ""
                exit_code = process.returncode

                # 构建结果消息，使其更结构化和人类可读
                execution_type = "文件执行" if params.file_path else "代码执行"
                execution_target = params.file_path if params.file_path else "代码片段"

                # 构建更友好、结构化的结果消息
                if exit_code == 0:
                    status = "成功"
                    result_sections = []

                    # 添加基本信息和输出内容
                    header = f"{execution_type}: {execution_target}"
                    if params.args:
                        header += f" (参数: {params.args})"

                    result_sections.append(header)
                    result_sections.append(f"状态: {status}")

                    # 添加输出内容（如果有）
                    if stdout_str:
                        result_sections.append(f"输出:\n{stdout_str}")
                    else:
                        result_sections.append("输出: (无)")

                    result_message = "\n".join(result_sections)
                else:
                    status = f"失败 (退出码: {exit_code})"
                    result_sections = []

                    # 添加基本信息
                    header = f"{execution_type}: {execution_target}"
                    if params.args:
                        header += f" (参数: {params.args})"

                    result_sections.append(header)
                    result_sections.append(f"状态: {status}")

                    # 添加输出和错误信息
                    if stdout_str:
                        result_sections.append(f"标准输出:\n{stdout_str}")

                    if stderr_str:
                        result_sections.append(f"错误信息:\n{stderr_str}")

                    result_message = "\n".join(result_sections)

                # 构造详细信息JSON并保存到system字段（用于系统内部使用，不直接展示给用户）
                execution_info = {
                    "command": " ".join(cmd_args),
                    "execution_type": "file" if params.file_path else "code",
                    "target": params.file_path if params.file_path else "code_snippet",
                    "cwd": str(work_dir),
                    "args": params.args,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "exit_code": exit_code,
                    "success": exit_code == 0
                }

                system_info = json.dumps(execution_info, ensure_ascii=False)

                if params.code and temp_file.exists():
                    try:
                        # 删除临时文件
                        os.unlink(temp_file)
                    except Exception as e:
                        logger.warning(f"删除临时文件失败: {e}")

                if exit_code == 0:
                    result = ToolResult(
                        content=result_message,
                        system=system_info,
                    )
                else:
                    result = ToolResult(
                        error=result_message,
                    )
                return result

            except asyncio.TimeoutError:
                # 超时，强制终止进程
                if process.returncode is None:
                    try:
                        process.kill()
                        await process.wait()
                    except:
                        pass

                if params.code and temp_file.exists():
                    try:
                        # 删除临时文件
                        os.unlink(temp_file)
                    except Exception as e:
                        logger.warning(f"删除临时文件失败: {e}")

                execution_type = "文件执行" if params.file_path else "代码执行"
                execution_target = params.file_path if params.file_path else "代码片段"

                timeout_message = (
                    f"{execution_type}: {execution_target}\n"
                    f"状态: 执行超时 ({params.timeout}秒)\n"
                    f"原因: 代码执行时间超过了设定的时间限制"
                )

                return ToolResult(
                    error=timeout_message
                )

        except Exception as e:
            logger.exception(f"执行Python代码时出错: {e}")
            error_message = (
                f"执行错误\n"
                f"错误类型: {type(e).__name__}\n"
                f"错误详情: {e!s}"
            )
            return ToolResult(
                error=error_message
            )

    async def get_tool_detail(self, tool_context: ToolContext, result: ToolResult, arguments: Dict[str, Any] = None) -> Optional[ToolDetail]:
        """
        根据工具执行结果获取对应的ToolDetail

        Args:
            tool_context: 工具上下文
            result: 工具执行的结果
            arguments: 工具执行的参数字典

        Returns:
            Optional[ToolDetail]: 工具详情对象，可能为None
        """
        if not result.ok and not result.error:
            return None

        # 获取代码内容
        code = ""
        if arguments.get("file_path"):
            # 如果是文件执行，读取文件内容
            file_path, error = self.get_safe_path(arguments.get("file_path"))
            if not error and file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        code = f.read()
                except Exception as e:
                    logger.warning(f"读取文件内容失败: {e}")
                    code = f"# 无法读取文件内容: {file_path}\n# 错误: {e}"
            else:
                code = f"# 文件不存在或路径错误: {arguments.get('file_path')}"
        elif arguments.get("code"):
            # 如果是代码执行，直接使用代码参数
            code = arguments.get("code")
        else:
            code = "# 没有提供代码内容"

        # 获取命令行参数
        args = arguments.get("args")

        # 尝试从result.system获取详细信息
        execution_info = {}
        if result.system:
            try:
                execution_info = json.loads(result.system)
            except Exception as e:
                logger.warning(f"解析执行信息失败: {e}")

        # 获取stdout、stderr和exit_code
        stdout = execution_info.get("stdout", "")
        stderr = execution_info.get("stderr", "")
        exit_code = execution_info.get("exit_code", 0)
        success = execution_info.get("success", result.ok)

        # 如果没有从system中获取到信息，则使用result中的内容
        if not stdout and not stderr:
            if result.ok:
                stdout = result.content
            else:
                stderr = result.error

        # 创建脚本执行内容对象
        script_content = FileContent(
            file_name="",
            content=code,
        )

        # 返回工具详情
        return ToolDetail(
            type=DisplayType.CODE,
            data=script_content
        )

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """
        获取工具调用后的友好动作和备注
        """
        action_type = "执行Python文件" if arguments.get("file_path") else "执行Python代码"
        action_target = arguments.get("file_path", "代码片段")

        return {
            "action": f"{action_type}",
            "remark": f"{action_target}"
        }

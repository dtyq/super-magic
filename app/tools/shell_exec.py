import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from agentlang.logger import get_logger
from agentlang.tools.tool_result import ToolResult
from app.core.entity.message.server_message import DisplayType, TerminalContent, ToolDetail
from app.core.entity.tool.tool_result import TerminalToolResult
from app.tools.core import BaseToolParams, tool
from app.tools.workspace_guard_tool import WorkspaceGuardTool

logger = get_logger(__name__)


class ShellExecParams(BaseToolParams):
    """Shell命令执行参数"""
    command: str = Field(
        ...,
        description="要执行的 shell 命令"
    )
    cwd: Optional[str] = Field(
        None,
        description="命令执行的工作目录（可选）"
    )
    timeout: int = Field(
        60,
        description="命令执行超时时间（秒），默认 60 秒"
    )


@tool()
class ShellExec(WorkspaceGuardTool[ShellExecParams]):
    """
    Shell命令执行工具，用于执行系统命令。

    使用场景：
    - 执行系统命令
    - 运行脚本
    - 管理进程
    - 文件操作

    注意：
    - 命令将在系统 shell 中执行
    - 支持设置工作目录
    - 可以设置超时时间
    - 只允许执行白名单中的安全命令，绝对不能执行有害命令
    - 某些危险操作（如删除）需要额外确认
    - 支持安全的复合命令执行（例如：mkdir -p /path && curl -o /file）
    - 尽量一次只执行一个命令，尽量不要执行复合命令
    """

    # 命令白名单配置
    SAFE_COMMANDS: Dict[str, Set[str]] = {
        # 文件和目录操作
        "ls": {"ls", "ls -l", "ls -la", "ls -lh", "ls -lah"},
        "cd": {"cd", "cd ..", "cd -"},
        "pwd": {"pwd"},
        "mkdir": {"mkdir", "mkdir -p"},
        "cp": {"cp", "cp -r", "cp -R"},
        "mv": {"mv"},
        "cat": {"cat"},
        "head": {"head", "head -n"},
        "tail": {"tail", "tail -n", "tail -f"},
        "touch": {"touch"},
        "chmod": {"chmod +x", "chmod 644", "chmod 755"},
        "find": {"find . -name", "find . -type", "find * -name", "find * -type"},
        # 进程管理
        "ps": {"ps", "ps aux", "ps -ef"},
        "kill": {"kill", "kill -9", "kill -15"},
        "pkill": {"pkill", "pkill -f"},
        # 系统信息
        "df": {"df", "df -h"},
        "du": {"du", "du -h", "du -sh"},
        "free": {"free", "free -h", "free -m"},
        "top": {"top -n"},
        "htop": {"htop"},
        # 网络工具
        "ping": {"ping -c"},
        "curl": {"curl", "curl -I", "curl -L", "curl -O", "curl -o"},
        "wget": {"wget"},
        "netstat": {"netstat", "netstat -an", "netstat -tulpn"},
        "ss": {"ss", "ss -tulpn"},
        # 包管理
        "pip": {"pip list", "pip show", "pip install", "pip uninstall"},
        "pip3": {"pip3 list", "pip3 show", "pip3 install", "pip3 uninstall"},
        "npm": {"npm list", "npm install", "npm uninstall", "npm run"},
        "yarn": {"yarn", "yarn add", "yarn remove", "yarn install"},
        # 压缩和解压
        "tar": {"tar -czf", "tar -xzf", "tar -cjf", "tar -xjf"},
        "zip": {"zip", "zip -r"},
        "unzip": {"unzip"},
        # Git 操作
        "git": {
            "git status",
            "git log",
            "git branch",
            "git checkout",
            "git pull",
            "git push",
            "git fetch",
            "git merge",
            "git add",
            "git commit",
            "git diff",
            "git show",
            "git remote",
            "git clone",
            "git init",
        },
        # 文本处理
        "grep": {"grep", "grep -r", "grep -i", "grep -v"},
        "sed": {"sed 's/", "sed -i 's/"},
        "awk": {"awk '{print", "awk -F"},
        "wc": {"wc", "wc -l", "wc -w"},
        "sort": {"sort", "sort -r", "sort -n"},
        "uniq": {"uniq", "uniq -c"},
        # Python 相关
        "python": {"python", "python3", "python -m", "python3 -m"},
        "pytest": {"pytest", "pytest -v", "pytest -k"},
        "coverage": {"coverage run", "coverage report"},
        # 环境变量
        "env": {"env", "env | grep"},
        "export": {"export"},
        "echo": {"echo", "echo $"},
    }

    # 允许的命令分隔符
    ALLOWED_SEPARATORS = ["&&", ";"]

    def _split_commands(self, command: str) -> List[str]:
        """
        将复合命令拆分为单个命令列表

        Args:
            command: 可能包含分隔符的命令字符串

        Returns:
            List[str]: 拆分后的命令列表
        """
        # 先保存分隔符用于临时替换
        temp_replacements = {}
        preserved_command = command

        # 临时替换引号内的内容以防止错误拆分
        in_single_quote = False
        in_double_quote = False
        quote_content = ""
        i = 0
        quote_start = -1

        while i < len(preserved_command):
            char = preserved_command[i]
            if char == "'" and not in_double_quote:
                if in_single_quote:
                    in_single_quote = False
                    quote_content = preserved_command[quote_start:i+1]
                    placeholder = f"__QUOTE_{len(temp_replacements)}__"
                    temp_replacements[placeholder] = quote_content
                    preserved_command = preserved_command[:quote_start] + placeholder + preserved_command[i+1:]
                    i = quote_start + len(placeholder)
                    continue
                else:
                    in_single_quote = True
                    quote_start = i
            elif char == '"' and not in_single_quote:
                if in_double_quote:
                    in_double_quote = False
                    quote_content = preserved_command[quote_start:i+1]
                    placeholder = f"__QUOTE_{len(temp_replacements)}__"
                    temp_replacements[placeholder] = quote_content
                    preserved_command = preserved_command[:quote_start] + placeholder + preserved_command[i+1:]
                    i = quote_start + len(placeholder)
                    continue
                else:
                    in_double_quote = True
                    quote_start = i
            i += 1

        # 使用正则表达式拆分命令
        # 注意：这个正则表达式匹配命令分隔符（&& 或 ;）
        commands = []
        for separator in self.ALLOWED_SEPARATORS:
            if separator in preserved_command:
                preserved_command = preserved_command.replace(separator, "##SEP##")

        raw_commands = preserved_command.split("##SEP##")

        # 恢复原始引号内容
        for cmd in raw_commands:
            cmd = cmd.strip()
            if not cmd:
                continue

            # 恢复所有临时替换
            for placeholder, original in temp_replacements.items():
                cmd = cmd.replace(placeholder, original)

            commands.append(cmd)

        return commands

    def _is_command_safe(self, command: str) -> bool:
        """
        检查命令是否在白名单中

        Args:
            command: 要检查的命令

        Returns:
            bool: 命令是否安全
        """
        # 分割命令和参数
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return False

        base_cmd = cmd_parts[0]

        # 检查基础命令是否在白名单中
        if base_cmd not in self.SAFE_COMMANDS:
            return False

        # 检查完整命令模式是否匹配白名单规则
        for safe_pattern in self.SAFE_COMMANDS[base_cmd]:
            pattern = f"^{safe_pattern.replace('*', '.*')}.*$"
            if re.match(pattern, command):
                return True

        return False

    def _sanitize_command(self, command: str) -> str:
        """
        清理和规范化命令，但保留允许的分隔符

        Args:
            command: 原始命令

        Returns:
            str: 清理后的命令
        """
        # 移除危险的 shell 操作符，但保留允许的分隔符
        dangerous_operators = ["|", ">", "<", "`", "$", "\\"]
        cleaned_command = command

        for op in dangerous_operators:
            cleaned_command = cleaned_command.replace(op, "")

        # 移除多余的空格，但保留命令之间的分隔
        for sep in self.ALLOWED_SEPARATORS:
            cleaned_command = cleaned_command.replace(sep, f" {sep} ")

        # 规范化空格
        cleaned_command = " ".join(filter(None, cleaned_command.split()))

        return cleaned_command

    def _validate_commands(self, commands: List[str]) -> Tuple[bool, Optional[str]]:
        """
        验证所有拆分后的命令是否安全

        Args:
            commands: 拆分后的命令列表

        Returns:
            Tuple[bool, Optional[str]]: (是否全部安全, 错误信息)
        """
        for cmd in commands:
            if not self._is_command_safe(cmd):
                return False, f"命令不在安全白名单中: {cmd}"
        return True, None

    def _check_workspace_path_safety(self, command: str) -> bool:
        """
        检查命令中的路径是否都在工作区内

        Args:
            command: 要检查的命令

        Returns:
            bool: 路径是否安全
        """
        # 提取命令中的所有路径参数
        # 这是一个简化的实现，可能需要更复杂的逻辑来处理所有情况
        workspace_path = str(self.base_dir)

        # 简单检查命令中提到的路径是否都在工作区内
        words = command.split()
        for word in words:
            if word.startswith('/') and not word.startswith(workspace_path):
                # 检查是否是工作区路径
                if not any(workspace_path in word for workspace_path in ['.workspace', 'super-magic/.workspace']):
                    return False

        return True

    async def execute(self, tool_context: ToolContext, params: ShellExecParams) -> TerminalToolResult:
        """
        执行 shell 命令，支持复合命令

        Args:
            tool_context: 工具上下文
            params: 参数对象，包含命令、工作目录和超时时间

        Returns:
            TerminalToolResult: 包含执行结果的结构化结果对象
        """
        try:
            # 处理工作目录
            work_dir = self.base_dir
            if params.cwd:
                # 使用父类方法获取安全的工作目录路径
                cwd_path, error = self.get_safe_path(params.cwd)
                if error:
                    return TerminalToolResult(
                        error=error,
                        command=params.command
                    )
                work_dir = cwd_path

            # 确保工作目录存在
            if not work_dir.exists():
                return TerminalToolResult(
                    error=f"工作目录不存在: {work_dir}",
                    command=params.command
                )

            # 检查是否是复合命令
            if any(sep in params.command for sep in self.ALLOWED_SEPARATORS):
                # 拆分命令
                commands = self._split_commands(params.command)

                # 验证所有命令是否安全
                all_safe, error_msg = self._validate_commands(commands)
                if not all_safe:
                    return TerminalToolResult(
                        error=error_msg,
                        command=params.command
                    )

                # 检查所有命令中的路径是否安全
                for cmd in commands:
                    if not self._check_workspace_path_safety(cmd):
                        return TerminalToolResult(
                            error=f"命令包含工作区外的路径，不允许执行: {cmd}",
                            command=params.command
                        )

                # 对于复合命令，保留分隔符并清理危险操作符
                cleaned_command = self._sanitize_command(params.command)

                logger.debug(f"执行复合命令: {cleaned_command}, 工作目录: {work_dir}")

            else:
                # 单个命令，使用原有逻辑处理
                cleaned_command = self._sanitize_command(params.command)
                if not self._is_command_safe(cleaned_command):
                    return TerminalToolResult(
                        error=f"命令不在安全白名单中: {params.command}",
                        command=params.command
                    )

                # 检查路径安全性
                if not self._check_workspace_path_safety(cleaned_command):
                    return TerminalToolResult(
                        error=f"命令包含工作区外的路径，不允许执行: {cleaned_command}",
                        command=params.command
                    )

                logger.debug(f"执行命令: {cleaned_command}, 工作目录: {work_dir}")

            # 创建结果对象
            result = TerminalToolResult(command=cleaned_command, content="命令执行中...")

            env_vars = {
                **os.environ,
                'PYTHONIOENCODING': 'utf-8',
                'MPLCONFIGDIR': '/root/.config/matplotlib',
                'LC_ALL': 'C.UTF-8',
                'LANG': 'C.UTF-8'
            }

            # 创建子进程
            process = await asyncio.create_subprocess_shell(
                cleaned_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
                env=env_vars,
            )

            try:
                # 等待进程完成，带超时
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=params.timeout
                )
                stdout_str = stdout.decode().strip() if stdout else ""
                stderr_str = stderr.decode().strip() if stderr else ""
                exit_code = process.returncode

                # 设置退出码
                result.set_exit_code(exit_code)

                # 构建结构化内容
                if exit_code == 0:
                    # 成功情况
                    content = "命令执行成功\n"
                    if stdout_str:
                        content += f"stdout:\n{stdout_str}\n"
                    if stderr_str:
                        content += f"stderr:\n{stderr_str}\n"
                    result.content = content.strip()
                else:
                    # 失败情况
                    error_content = f"命令执行失败 (退出码: {exit_code})\n"
                    if stdout_str:
                        error_content += f"stdout:\n{stdout_str}\n"
                    if stderr_str:
                        error_content += f"stderr:\n{stderr_str}\n"
                    result.content = error_content.strip()
                    result.ok = False

                # 构造命令信息JSON并保存到system字段
                system_info = {
                    "command": cleaned_command,
                    "cwd": str(work_dir),
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "exit_code": exit_code,
                    "execution_time": params.timeout,
                }
                result.system = json.dumps(system_info, ensure_ascii=False)

                return result

            except asyncio.TimeoutError:
                # 超时，强制终止进程
                if process.returncode is None:
                    try:
                        process.kill()
                        await process.wait()
                    except:
                        pass

                return TerminalToolResult(
                    error=f"命令执行超时 ({params.timeout}秒): {cleaned_command}",
                    command=cleaned_command,
                    exit_code=-1  # 使用-1表示超时
                )

        except Exception as e:
            logger.exception(f"执行命令时出错: {e}")
            return TerminalToolResult(
                error=f"执行命令时出错: {e}",
                command=params.command,
                exit_code=-2  # 使用-2表示异常
            )

    async def get_after_tool_call_friendly_action_and_remark(self, tool_name: str, tool_context: ToolContext, result: ToolResult, execution_time: float, arguments: Dict[str, Any] = None) -> Dict:
        """
        获取工具调用后的友好动作和备注
        """
        command = arguments.get("command", "") if arguments else ""
        return {
            "action": "执行Shell命令",
            "remark": command
        }

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
        if not result.ok:
            return None

        if not isinstance(result, TerminalToolResult):
            logger.warning("结果不是TerminalToolResult类型")
            return None

        # 获取命令、输出和退出码
        command = result.command if hasattr(result, 'command') else arguments.get("command", "")
        output = result.content if result.content else ""
        exit_code = result.exit_code if hasattr(result, 'exit_code') else 0

        # 创建终端内容对象
        terminal_content = TerminalContent(
            command=command,
            output=output,
            exit_code=exit_code
        )

        # 返回工具详情
        return ToolDetail(
            type=DisplayType.TERMINAL,
            data=terminal_content
        )

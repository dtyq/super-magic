"""
文件监听服务，启动上传文件进程
"""

import asyncio
import os
import subprocess
from pathlib import Path

from agentlang.event.event import Event, EventType
from agentlang.logger import get_logger, setup_logger
from agentlang.utils.process_manager import ProcessManager
from app.core.context.agent_context import AgentContext
from app.utils.executable_utils import get_executable_command

logger = get_logger(__name__)

def run_storage_uploader_process(cmd, project_root, log_level="INFO"):
    """存储上传器子进程运行的函数"""
    try:
        setup_logger(log_name="storage_uploader_subprocess", console_level=log_level)
        logger_proc = get_logger("storage_uploader_subprocess_logger")
        logger_proc.info(f"存储上传器子进程启动: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            cwd=str(project_root)
        )
        for line in iter(process.stdout.readline, ''):
            if line:
                logger_proc.info(f"存储上传器: {line.rstrip()}")
        process.stdout.close()
        return_code = process.wait()
        logger_proc.info(f"存储上传进程已退出，返回码: {return_code}")
    except Exception as e:
        logger.error(f"存储上传器子进程异常: {e}")
        import traceback
        logger.error(traceback.format_exc())

class FileListenerService:
    """文件监听服务，启动上传文件的进程"""

    @staticmethod
    def register_standard_listeners(agent_context: AgentContext) -> None:
        """
        注册标准的文件相关事件监听器

        Args:
            agent_context: 代理上下文对象
        """
        agent_context.add_event_listener(
            EventType.AFTER_INIT,
            FileListenerService._handle_after_init
        )
        logger.info("已注册文件监听服务，用于在初始化后启动存储上传器。")

    @staticmethod
    async def _start_uploader_process(agent_context: AgentContext) -> None:
        """
        启动存储上传程序（使用ProcessManager创建和管理子进程）
        """
        try:
            project_root = Path(__file__).resolve().parent.parent.parent.parent

            sandbox_id = agent_context.get_sandbox_id()
            organization_code = agent_context.get_organization_code()
            workspace_dir = agent_context.get_workspace_dir()
            log_level_to_pass = os.getenv("LOG_LEVEL", "INFO").upper()

            base_cmd = get_executable_command()
            cmd = base_cmd + [
                "storage-uploader",
                "watch",
                "--dir", str(workspace_dir),
                "--log-level", log_level_to_pass
            ]

            if sandbox_id:
                cmd.extend(["--sandbox", sandbox_id])
            else:
                logger.warning("未在AgentContext中找到沙盒ID，上传程序可能无法正常注册文件。")

            if organization_code:
                cmd.extend(["--organization-code", organization_code])

            logger.info(f"准备启动存储上传程序 (ProcessManager模式): {' '.join(cmd)}")
            sandbox_info = f"沙盒ID: {sandbox_id}" if sandbox_id else "未设置沙盒ID"
            logger.info(f"使用 {sandbox_info}")

            await FileListenerService._terminate_existing_uploader()

            process_manager = ProcessManager.get_instance()
            worker_name = "storage_uploader"

            pid = await process_manager.start_worker(
                worker_name,
                run_storage_uploader_process,
                cmd,
                str(project_root),
                log_level_to_pass
            )

            logger.info(f"存储上传器子进程已启动，PID: {pid}")

        except Exception as e:
            logger.error(f"启动存储上传程序失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    @staticmethod
    async def _terminate_existing_uploader() -> None:
        """终止现有的上传进程"""
        try:
            process_manager = ProcessManager.get_instance()
            worker_name = "storage_uploader"
            worker_info = await process_manager.get_worker_info(worker_name)
            if worker_info and worker_name in worker_info:
                success = await process_manager.stop_worker(worker_name)
                if success:
                    logger.info("已终止之前的存储上传子进程。")
                else:
                    logger.warning("终止之前的存储上传子进程失败。")
        except Exception as e:
            logger.error(f"终止之前的上传进程失败: {e}")

    @staticmethod
    async def _handle_after_init(event: Event) -> None:
        """
        处理初始化完成事件，启动存储上传程序。

        Args:
            event: 事件对象，应包含 agent_context 在 event.data 中。
        """
        try:
            agent_context = event.data.agent_context
            if agent_context:
                project_root = Path(__file__).resolve().parent.parent.parent.parent 
                credentials_dir = project_root / ".credentials"
                if not credentials_dir.exists():
                    try:
                        credentials_dir.mkdir(parents=True, exist_ok=True)
                        logger.info(f"已创建凭证目录: {credentials_dir}")
                    except Exception as e_mkdir:
                        logger.error(f"创建凭证目录失败 ({credentials_dir}): {e_mkdir}")

                asyncio.create_task(FileListenerService._start_uploader_process(agent_context))
                logger.info("存储上传程序启动任务已创建 (ProcessManager模式)。")

        except AttributeError:
             logger.error("处理初始化事件失败：事件数据结构不符合预期 (缺少 agent_context)。")
        except Exception as e:
            logger.error(f"处理初始化事件并启动上传程序时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())

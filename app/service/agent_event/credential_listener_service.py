"""
文件监听服务，启动上传文件进程
"""

import asyncio
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

from agentlang.event.event import Event, EventType
from agentlang.logger import get_logger, setup_logger
from app.core.context.agent_context import AgentContext

logger = get_logger(__name__)

def run_tos_uploader(cmd, project_root, log_level="INFO"):
    """TOS上传器子进程运行的函数
    
    Args:
        cmd: 命令行参数列表
        project_root: 项目根目录
        log_level: 日志级别
    """
    try:
        # 设置子进程的日志
        setup_logger(log_name="app", console_level=log_level)
        logger = get_logger("tos_uploader_process")

        logger.info(f"TOS上传器子进程启动: {' '.join(cmd)}")

        # 启动上传程序进程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(project_root)
        )

        # 读取并记录输出
        for line in iter(process.stdout.readline, ''):
            if line:
                logger.info(f"TOS上传器: {line.rstrip()}")

        process.stdout.close()
        return_code = process.wait()
        logger.info(f"TOS上传进程已退出，返回码: {return_code}")

    except Exception as e:
        logger.error(f"TOS上传器子进程异常: {e}")
        import traceback
        logger.error(traceback.format_exc())

class FileListenerService:
    """文件监听服务，启动上传文件的进程"""

    # 使用类变量跟踪上传进程
    _uploader_process = None

    @staticmethod
    def register_standard_listeners(agent_context: AgentContext) -> None:
        """
        注册标准的文件相关事件监听器
        
        Args:
            agent_context: 代理上下文对象
        """
        # 监听初始化完成事件
        agent_context.add_event_listener(
            EventType.AFTER_INIT, 
            FileListenerService._handle_after_init
        )

        # 监听客户端聊天事件
        # agent_context.add_event_listener(
        #     EventType.AFTER_CLIENT_CHAT,
        #     FileListenerService._handle_after_client_chat
        # )

        logger.info("已注册文件监听器")

    @staticmethod
    async def _start_tos_uploader(agent_context: AgentContext) -> None:
        """
        启动TOS上传程序（使用multiprocessing创建独立子进程）
        
        Args:
            agent_context: 代理上下文对象
        """
        try:
            # 获取项目根目录
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            uploader_path = project_root / "bin" / "tos_uploader.py"

            if not uploader_path.exists():
                logger.error(f"TOS上传程序不存在: {uploader_path}")
                return

            # 获取沙盒ID
            sandbox_id = agent_context.get_sandbox_id()
            if not sandbox_id:
                logger.warning("AgentContext中没有设置沙盒ID，TOS上传程序可能无法正常工作")

            # 获取组织编码
            organization_code = agent_context.get_organization_code()

            # 工作目录
            workspace_dir = agent_context.get_workspace_dir()

            # 使用和当前相同的日志级别
            log_level = os.getenv("LOG_LEVEL", "INFO")

            # 构建命令
            cmd = [
                sys.executable,  # 使用当前Python解释器
                str(uploader_path),
                "watch",
                "--dir", workspace_dir,
                "--use-context"  # 使用config/upload_credentials.json
            ]

            # 添加沙盒ID（如果有）
            if sandbox_id:
                cmd.extend(["--sandbox", sandbox_id])

            # 如果有组织编码，添加
            if organization_code:
                cmd.extend(["--organization-code", organization_code])

            # 记录启动命令
            logger.info(f"准备启动TOS上传程序（子进程模式）: {' '.join(cmd)}")

            sandbox_info = f"沙盒ID: {sandbox_id}" if sandbox_id else "未设置沙盒ID"
            logger.info(f"使用 {sandbox_info}")

            # 终止现有进程（如果有）
            await FileListenerService._terminate_existing_uploader()

            # 创建新的子进程运行上传器
            loop = asyncio.get_event_loop()

            def start_uploader_process():
                process = multiprocessing.Process(
                    target=run_tos_uploader,
                    args=(cmd, project_root, log_level),
                    name="TOSUploader"
                )
                process.daemon = True  # 设置为守护进程，主进程结束时自动结束
                process.start()
                return process

            # 使用run_in_executor启动子进程
            process = await loop.run_in_executor(None, start_uploader_process)

            # 保存进程引用
            FileListenerService._uploader_process = process

            logger.info(f"TOS上传器子进程已启动，PID: {process.pid}")

        except Exception as e:
            logger.error(f"启动TOS上传程序失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    @staticmethod
    async def _terminate_existing_uploader() -> None:
        """终止现有的上传进程"""
        if FileListenerService._uploader_process is not None:
            try:
                process = FileListenerService._uploader_process

                # 检查进程是否还在运行
                if process.is_alive():
                    # 使用loop.run_in_executor执行terminate操作
                    loop = asyncio.get_event_loop()

                    def terminate_process():
                        process.terminate()
                        process.join(timeout=3)  # 等待最多3秒
                        if process.is_alive():
                            logger.warning("TOS上传进程未能在超时时间内正常结束，强制终止")
                            process.kill()
                        return True

                    await loop.run_in_executor(None, terminate_process)
                    logger.info("已终止之前的TOS上传子进程")
                else:
                    logger.info("之前的TOS上传子进程已不在运行")

            except Exception as e:
                logger.error(f"终止之前的上传进程失败: {e}")

            # 重置进程引用
            FileListenerService._uploader_process = None

    @staticmethod
    async def _handle_after_init(event: Event) -> None:
        """
        处理初始化事件，启动上传程序
        
        Args:
            event: 事件对象
        """
        try:
            # 从事件数据中获取agent_context
            agent_context = event.data.agent_context

            if agent_context:
                # 确保凭证目录存在
                if not os.path.exists(".credentials"):
                    os.makedirs(".credentials", exist_ok=True)

                # 创建异步任务来启动TOS上传程序，不阻塞当前流程
                asyncio.create_task(FileListenerService._start_tos_uploader(agent_context))
                logger.info("TOS上传程序启动任务已创建（子进程模式）")

        except Exception as e:
            logger.error(f"处理初始化事件启动上传程序出错: {e}")

    # @staticmethod
    # async def _handle_after_init(event: Event) -> None:
    #     """
    #     处理初始化后事件，记录相关信息

    #     Args:
    #         event: 事件对象
    #     """
    #     try:
    #         # 从事件数据中安全地获取agent_context
    #         agent_context = None
    #         if hasattr(event.data, "agent_context") and event.data.agent_context:
    #             agent_context = event.data.agent_context
    #             logger.info("已捕获初始化完成事件，agent_context已设置")
    #         else:
    #             logger.info("初始化事件数据中未找到agent_context属性")

    #     except Exception as e:
    #         logger.error(f"处理初始化完成事件出错: {e}") 

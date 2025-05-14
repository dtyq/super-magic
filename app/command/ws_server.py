"""
WebSocket服务器命令模块
"""
import asyncio
import importlib
import importlib.metadata
import os
import signal
import socket
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.config import Config

from app.api.middleware import RequestLoggingMiddleware
from app.api.routes import api_router
from app.api.routes.websocket import router as websocket_router
from app.service.agent_dispatcher import AgentDispatcher
from agentlang.logger import get_logger
from app.service.idle_monitor_service import IdleMonitorService
from agentlang.utils.process_manager import ProcessManager

# 获取日志记录器
logger = get_logger(__name__)

# 存储服务器实例和全局变量
ws_server = None
_app = None  # 存储FastAPI应用实例的内部变量


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期管理"""
    # 启动时
    logger.info("服务正在启动...")

    # 打印Git commit ID
    git_commit_id = os.getenv("GIT_COMMIT_ID", "未知")
    logger.info(f"当前版本Git commit ID: {git_commit_id}")

    logger.info("WebSocket服务将监听端口：8002")
    yield
    # 关闭时
    logger.info("服务正在关闭...")


def create_app() -> FastAPI:
    """创建并配置FastAPI应用实例"""
    # 创建 FastAPI 应用
    app = FastAPI(
        title="Super Magic API",
        description="Super Magic API 和 WebSocket 服务",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 添加请求日志中间件
    app.add_middleware(RequestLoggingMiddleware)

    # 添加 CORS 中间件 - 修改配置以解决浏览器跨域问题
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 允许所有源，也可以指定特定域名，如 ["http://localhost:3000"]
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],  # 明确指定允许的方法
        allow_headers=["*"],  # 允许所有头信息
        expose_headers=["*"],  # 暴露所有头信息
        max_age=600,  # 预检请求结果缓存时间，单位秒
    )

    # 注册路由
    app.include_router(api_router)
    app.include_router(websocket_router)

    return app


def get_app() -> FastAPI:
    """获取FastAPI应用实例，避免循环导入

    Returns:
        FastAPI: 应用实例
    """
    global _app
    if _app is None:
        _app = create_app()
    return _app


class CustomServer(uvicorn.Server):
    """自定义 uvicorn Server 类，用于正确处理信号"""

    def install_signal_handlers(self) -> None:
        """不安装信号处理器，使用我们自己的处理方式"""
        pass

    async def shutdown(self, sockets=None):
        """尝试优雅地关闭服务器"""
        logger.info("正在关闭 uvicorn 服务器...")
        await super().shutdown(sockets=sockets)


def start_ws_server():
    """启动WebSocket服务器"""
    # 获取环境变量中的日志级别
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # 获取FastAPI应用实例
    app = get_app()

    # 创建一个仅启动WS服务器的异步函数
    async def run_ws_only():
        process_manager = ProcessManager.get_instance()
        # 获取并处理entry_points
        try:
            # 使用pkg_resources处理entry_points
            process_entry_points = list(importlib.metadata.entry_points(group='command.ws_server.process'))

            logger.info(f"找到 {len(process_entry_points)} 个 ws_server 进程 entry_points")
            
            # 加载所有找到的entry_points
            for entry_point in process_entry_points:
                logger.info(f"正在加载进程: {entry_point.name}")
                value = entry_point.value
                value = value.split(":")
                module_name = value[0]
                function_name = value[1]
                logger.info(f"加载模块: {module_name}, 函数: {function_name}")
                loader = importlib.import_module(module_name)
                await loader.load(process_manager, log_level)
        except Exception as e:
            logger.error(f"加载entry_points时出错: {e}")

        dispatcher = AgentDispatcher.get_instance()
        await dispatcher.setup()

        IdleMonitorService.get_instance().start()

        # 使用与原main()函数相似的代码，但只启动WebSocket服务
        # 创建并配置WebSocket socket
        ws_port = 8002
        ws_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ws_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ws_socket.bind(("0.0.0.0", ws_port))

        logger.info(f"WebSocket服务将监听端口：{ws_port}")

        # 创建uvicorn配置
        uvicorn_config = Config(
            app,
            host="0.0.0.0",
            port=0,
            log_level=log_level.lower(),
            ws_ping_interval=None,
        )

        # 启动服务器
        global ws_server
        ws_server = CustomServer(uvicorn_config)

        # 同样需要处理信号
        shutdown_event = asyncio.Event()

        # 设置信号处理器
        def handle_signal(sig, frame):
            logger.info(f"收到信号 {sig}，准备关闭服务...")
            shutdown_event.set()

        # 注册信号处理器
        original_sigint_handler = signal.getsignal(signal.SIGINT)
        original_sigterm_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            # 启动WS服务
            ws_task = asyncio.create_task(ws_server.serve(sockets=[ws_socket]))

            # 等待关闭事件
            await shutdown_event.wait()
            logger.info("正在停止WebSocket服务...")
        except Exception as e:
            logger.error(f"WebSocket服务运行过程中出现错误: {e}")
        finally:
            # 优雅关闭服务器
            if ws_server:
                ws_server.should_exit = True

            # 等待一小段时间让lifespan正常关闭
            await asyncio.sleep(0.5)

            # 取消服务任务
            ws_task.cancel()

            await process_manager.stop_all()

            IdleMonitorService.get_instance().stop()

            try:
                # 等待任务完成
                await asyncio.gather(ws_task, return_exceptions=True)
            except Exception as e:
                logger.error(f"关闭WebSocket服务时出现错误: {e}")

            # 恢复原始信号处理器
            signal.signal(signal.SIGINT, original_sigint_handler)
            signal.signal(signal.SIGTERM, original_sigterm_handler)

            # 关闭socket
            ws_socket.close()
            logger.info("WebSocket服务已完全关闭")

    # 运行异步函数
    asyncio.run(run_ws_only())

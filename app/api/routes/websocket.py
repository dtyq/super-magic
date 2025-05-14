import asyncio
import json
import os
import traceback

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.dto.base import WebSocketMessage
from app.service.agent_dispatcher import AgentDispatcher
from app.core.entity.event.event import AfterClientChatEventData
from agentlang.event.data import (
    AgentSuspendedEventData, ErrorEventData
)
from app.core.entity.message.client_message import ChatClientMessage, ContextType, InitClientMessage
from app.core.entity.message.message import MessageType
from agentlang.event.event import EventType
from app.core.stream.websocket_stream import WebSocketStream
from agentlang.logger import get_logger
from agentlang.utils.snowflake import Snowflake

# 创建路由器
router = APIRouter(prefix="/ws")

logger = get_logger(__name__)

class WebSocketManager:
    """WebSocket连接管理器，处理WebSocket连接和消息转发"""

    _instance = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls):
        """获取WebSocketManager单例实例"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = WebSocketManager()
                    logger.info("WebSocketManager单例已初始化")
        return cls._instance

    def __init__(self):
        """初始化WebSocketManager"""
        # 任务管理
        self.manager_task: asyncio.Task = None
        self.worker_task: asyncio.Task = None

        # 创建AgentDispatcher实例
        self.agent_dispatcher = AgentDispatcher.get_instance()

    async def handle_chat(self, websocket: WebSocket, message: ChatClientMessage):
        """处理聊天消息"""
        agent_context = self.agent_dispatcher.agent_context

        await agent_context.dispatch_event(EventType.AFTER_CLIENT_CHAT, AfterClientChatEventData(
            agent_context=agent_context,
            client_message=message
        ))

        await self.agent_dispatcher.dispatch_agent(message)

    async def handle_workspace_init(self, message: InitClientMessage):
        """处理工作区初始化消息"""
        logger.info(f"收到{MessageType.INIT}消息")

        # 初始化工作区
        await self.agent_dispatcher.initialize_workspace(message)

        logger.info("工作区初始化完成")

    async def manager_coroutine(self, websocket: WebSocket):
        """管理WebSocket连接的主协程"""
        while True:
            try:
                # 接收消息
                data = await websocket.receive_text()
                logger.info(f"收到原始消息: {data}")

                # 解析 JSON 消息
                message_data = json.loads(data)

                # 基本消息结构验证
                ws_message = WebSocketMessage(**message_data)
                type = ws_message.type

                if type == MessageType.CHAT.value:
                    message = ChatClientMessage(**message_data)

                    # 处理不同类型的消息
                    if message.context_type == ContextType.NORMAL or message.context_type == ContextType.FOLLOW_UP:
                        # 取消当前正在运行的worker_task (如果存在)
                        await self.cancel_task()

                        # 创建新的worker_task，直接传递消息
                        self.worker_task = asyncio.create_task(self.worker_coroutine(websocket, message))
                        logger.info(f"已创建新的worker任务处理{'普通' if message.context_type == ContextType.NORMAL else '追问'}消息")
                        try:
                            await self.worker_task
                        except asyncio.CancelledError:
                            logger.info("已取消正在运行的worker任务")

                    elif message.context_type == ContextType.INTERRUPT:
                        logger.info("收到中断请求")
                        # 只取消任务，不创建新任务
                        await self.cancel_task()
                        # 发送挂起消息
                        await self.agent_dispatcher.agent_context.dispatch_event(EventType.AGENT_SUSPENDED, AgentSuspendedEventData(
                            agent_context=self.agent_dispatcher.agent_context,
                        ))

                    # 处理完 chat 的消息后退出循环
                    break

                elif type == MessageType.INIT.value:
                    message = InitClientMessage(**message_data)
                    await self.handle_workspace_init(message)

                else:
                    valid_actions = ", ".join([MessageType.CHAT.value, MessageType.INIT.value])
                    raise ValueError(f"不支持的消息类型: {type}，有效值为: {valid_actions}")
            except WebSocketDisconnect:
                logger.error(traceback.format_exc())
                logger.info("WebSocket连接断开")
                break
            except Exception as e:
                # 打印错误堆栈
                logger.error(traceback.format_exc())
                await self.agent_dispatcher.agent_context.dispatch_event(EventType.ERROR, ErrorEventData(
                    agent_context=self.agent_dispatcher.agent_context,
                    error_message="服务异常"
                ))
                break

    async def worker_coroutine(self, websocket: WebSocket, message: ChatClientMessage):
        """处理具体消息的工作协程"""
        snowflake = Snowflake.create_default()
        task_id = str(snowflake.get_id())
        self.agent_dispatcher.agent_context.set_task_id(task_id)

        await self.handle_chat(websocket, message)
        logger.info("工作协程处理完成")

    async def cancel_task(self):
        """取消任务"""
        if self.worker_task and not self.worker_task.done():
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                logger.info("已取消正在运行的worker任务")


# 创建WebSocketManager实例，但实际初始化将在首次get_instance调用时发生
# ws_manager = WebSocketManager()

@router.websocket("")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 端点，处理客户端消息并返回 SuperMagic 代理回复

    支持sync/sync-ack同步机制，确保任务继续执行并向客户端推送消息：
    - 客户端通过发送sync动作建立连接，
    - 服务端返回sync-ack响应，包含任务运行状态
    - 如果客户端断线，可以重新发送sync消息重连
    - 可选pull_history参数控制是否接收历史消息

    所有异常处理都由 websocket_route_handler 装饰器统一处理
    """
    await websocket.accept()

    logger.info("新的 WebSocket 连接已建立")

    # 获取WebSocketManager实例
    ws_manager = await WebSocketManager.get_instance()

    # 为新连接创建WebSocket流并添加到Agent上下文
    stream = WebSocketStream(websocket=websocket)
    ws_manager.agent_dispatcher.agent_context.add_stream(stream)

    try:
        # 创建管理协程
        ws_manager.manager_task = asyncio.create_task(ws_manager.manager_coroutine(websocket))

        # 等待管理协程完成
        await ws_manager.manager_task

        logger.info("manager协程结束运行")

    except Exception as e:
        logger.error(f"WebSocket连接异常: {e!s}")

        # 同样取消任何正在运行的任务
        if ws_manager.worker_task and not ws_manager.worker_task.done():
            ws_manager.worker_task.cancel()
            logger.info("已取消worker任务")

        if ws_manager.manager_task and not ws_manager.manager_task.done():
            ws_manager.manager_task.cancel()
            logger.info("已取消manager任务")
    finally:
        # 从Agent上下文中移除WebSocket流
        ws_manager.agent_dispatcher.agent_context.remove_stream(stream)

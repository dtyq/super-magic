import asyncio
import json
import os
import re
import shutil
import tempfile
import zipfile
from typing import Any, Dict, List, Optional

from agentlang.context.tool_context import ToolContext
from agentlang.environment import Environment
from agentlang.event.data import AfterInitEventData
from agentlang.event.event import EventType
from agentlang.logger import get_logger
from app.core.context.agent_context import AgentContext
from app.core.stream.base import Stream
from app.infrastructure.storage.base import BaseFileProcessor
from app.infrastructure.storage.factory import StorageFactory
from app.magic.agent import Agent
from app.paths import PathManager
from app.service.agent_event.file_storage_listener_service import FileStorageListenerService
from app.service.attachment_service import AttachmentService

logger = get_logger(__name__)


class AgentService:
    def is_support_fetch_workspace(self) -> bool:
        """是否支持获取工作空间
        
        Returns:
            bool: 是否支持获取工作空间
        """
        # 优先从环境变量获取，如果不存在则从配置文件获取
        env_value = Environment.get_env("FETCH_WORKSPACE", None, bool)
        if env_value is not None:
            return env_value

        # 从配置文件获取
        try:
            from agentlang.config.config import config
            return config.get("sandbox.fetch_workspace", False)
        except (ImportError, AttributeError):
            return False

    async def _download_and_check_project_archive_info(self, agent_context: AgentContext) -> bool:
        """
        下载并检查项目存档信息文件

        Args:
            agent_context: 代理上下文

        Returns:
            bool: 是否需要更新工作区
        """
        # 获取storage_service
        sts_token_refresh = agent_context.get_init_client_message_sts_token_refresh()
        metadata = agent_context.get_init_client_message_metadata()

        storage_service = await StorageFactory.get_storage(
            sts_token_refresh=sts_token_refresh,
            metadata=metadata
        )

        # 尝试下载项目存档信息文件
        project_archive_info_file_relative_path = PathManager.get_project_archive_info_file_relative_path()
        project_archive_info_file = PathManager.get_project_archive_info_file()

        project_archive_info_file_key = BaseFileProcessor.combine_path(dir_path=storage_service.credentials.get_dir(), file_path=project_archive_info_file_relative_path)
        # 判断文件是否存在
        if not await storage_service.exists(project_archive_info_file_key):
            logger.info(f"项目存档信息文件不存在: {project_archive_info_file_key}")
            return False
        logger.info(f"尝试下载项目存档信息文件: {project_archive_info_file_key}")
        info_file_stream = await storage_service.download(
            key=project_archive_info_file_key,
            options=None
        )

        # 解析远程版本信息
        remote_info = json.loads(info_file_stream.read().decode('utf-8'))
        remote_version = remote_info.get('version', 0)
        logger.info(f"远程项目存档信息版本号: {remote_version}")

        # 获取本地版本信息
        local_version = 0
        if os.path.exists(project_archive_info_file):
            with open(project_archive_info_file, 'r') as f:
                local_info = json.load(f)
                local_version = local_info.get('version', 0)
                logger.info(f"本地项目存档信息版本号: {local_version}")
        else:
            logger.info("本地项目存档信息文件不存在")

        # 如果远程版本小于等于本地版本，则不需要更新
        if remote_version <= local_version:
            logger.info(f"远程版本({remote_version})不大于本地版本({local_version})，无需更新工作区")
            return False

        logger.info(f"远程版本({remote_version})大于本地版本({local_version})，将更新工作区")

        # 版本较新，保存远程版本信息到本地
        project_schema_absolute_dir = PathManager.get_project_schema_absolute_dir()
        project_schema_absolute_dir.mkdir(exist_ok=True, parents=True)
        with open(project_archive_info_file, 'w') as f:
            json.dump(remote_info, f)
            logger.info(f"已更新本地项目存档信息文件: {project_archive_info_file}")
        return True

    async def download_and_extract_workspace(self, agent_context: AgentContext) -> None:
        """
        从OSS下载并解压工作区

        Args:
            agent_context: 代理上下文，包含存储配置和update_workspace状态

        Returns:
            bool: 下载和解压是否成功
        """
        # 获取配置
        sts_token_refresh = agent_context.get_init_client_message_sts_token_refresh()
        metadata = agent_context.get_init_client_message_metadata()

        storage_service = await StorageFactory.get_storage(
            sts_token_refresh=sts_token_refresh,
            metadata=metadata
        )

        # 下载并检查项目存档信息文件
        need_update = await self._download_and_check_project_archive_info(
            agent_context=agent_context
        )

        # 如果不需要更新工作区，则直接返回
        if not need_update or not self.is_support_fetch_workspace():
            logger.info("工作区不需要更新，跳过下载和解压")
            return

        # 从OSS下载project_archive.zip压缩包
        file_key = BaseFileProcessor.combine_path(dir_path=storage_service.credentials.get_dir(), file_path="project_archive.zip")
        logger.info(f"开始从OSS下载压缩包: {file_key}")
        file_stream = await storage_service.download(
            key=file_key,
            options=None
        )

        # 保存到临时文件
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        temp_zip_path = temp_zip.name
        temp_zip.close()

        # 写入临时文件
        with open(temp_zip_path, 'wb') as f:
            f.write(file_stream.read())

        logger.info(f"压缩包下载完成: {temp_zip_path}")
        # 打印压缩包大小
        zip_size = os.path.getsize(temp_zip_path)
        logger.info(f"压缩包大小: {zip_size} 字节 ({zip_size/1024/1024:.2f} MB)")

        # 清空现有目录
        workspace_dir = PathManager.get_workspace_dir()
        chat_history_dir = PathManager.get_chat_history_dir()
        if workspace_dir.exists():
            logger.info(f"清空现有工作区目录: {workspace_dir}")
            shutil.rmtree(workspace_dir)
        if chat_history_dir.exists():
            logger.info(f"清空现有聊天历史目录: {chat_history_dir}")
            shutil.rmtree(chat_history_dir)

        # 重新创建目录
        workspace_dir.mkdir(exist_ok=True)
        chat_history_dir.mkdir(exist_ok=True)

        # 解压缩文件
        project_root = PathManager.get_project_root()
        logger.info(f"开始解压文件到: {project_root}")
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            # 解压所有文件到项目根目录
            zip_ref.extractall(project_root)

        logger.info("工作区初始化压缩包解压完成")

        # 删除临时文件
        os.unlink(temp_zip_path)
        logger.info(f"临时文件已删除: {temp_zip_path}")

    def _save_init_client_message_to_credentials(self, agent_context: AgentContext) -> None:
        """
        保存客户端初始化消息

        Args:
            agent_context: 代理上下文，包含客户端初始化消息
        """
        try:
            init_client_message = agent_context.get_init_client_message()
            if init_client_message:
                init_client_message_file = PathManager.get_init_client_message_file()
                with open(init_client_message_file, "w", encoding="utf-8") as f:
                    json.dump(init_client_message.model_dump(), f, indent=2, ensure_ascii=False)

                logger.info(f"已保存客户端初始化消息到: {init_client_message_file}")
        except Exception as e:
            logger.error(f"保存客户端初始化消息时出错: {e}")

    async def init_workspace(
        self,
        agent_context: AgentContext,
    ):
        """
        初始化智能体

        Args:
            agent_context: 智能体上下文
        """

        for stream in agent_context.streams.values():
            agent_context.add_stream(stream)

        logger.info("超级麦吉初始化开始")

        # 初始化OSS凭证
        sts_token_refresh = agent_context.get_init_client_message_sts_token_refresh()
        metadata = agent_context.get_init_client_message_metadata()
        await StorageFactory.get_storage(
            sts_token_refresh=sts_token_refresh,
            metadata=metadata
        )

        # 保存 init_client_message 到 .credentials 目录
        self._save_init_client_message_to_credentials(agent_context)

        await self.download_and_extract_workspace(agent_context)

        # 创建 ToolContext 实例
        tool_context = ToolContext(metadata=agent_context.get_metadata())
        # 将 AgentContext 作为扩展注册
        tool_context.register_extension("agent_context", agent_context)

        after_init_data = AfterInitEventData(
            tool_context=tool_context,
            agent_context=agent_context,
            success=True
        )
        await agent_context.dispatch_event(EventType.AFTER_INIT, after_init_data)

        logger.info("超级麦吉初始化完成")

        return

    async def create_agent(
        self,
        agent_name: str,
        agent_context: AgentContext,
    ) -> Agent:
        """
        创建智能体实例

        Args:
            agent_type: 智能体类型名称
            stream_mode: 是否启用流式输出
            agent_context: 可选的代理上下文对象，将覆盖其他参数
            stream: 流式输出对象
            storage_credentials: 对象存储凭证，用于配置对象存储服务

        Returns:
            智能体实例和错误信息列表
        """

        try:
            agent = Agent(agent_name, agent_context)

            return agent
        except Exception as e:
            logger.error(f"创建SuperMagic实例时出错: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return None

    async def run_agent(
        self,
        agent: Agent,
    ):
        agent_context = agent.agent_context
        chat_client_message = agent_context.get_chat_client_message()
        query = chat_client_message.prompt
        if chat_client_message and hasattr(chat_client_message, "attachments") and chat_client_message.attachments:
            query = await self._process_attachments(agent_context, query, chat_client_message.attachments)

        try:
            await agent.run_main_agent(query)
        finally:
            # 持久化项目目录
            asyncio.create_task(
                FileStorageListenerService._archive_and_upload_project(agent_context)
            )

    def create_agent_context(
        self,
        stream_mode: bool,
        streams: Optional[List[Stream]] = [],
        agent_type: Optional[str] = None,
        llm: Optional[str] = None,
        task_id: Optional[str] = "",
        is_main_agent: bool = False,
        interrupt_queue: Optional[asyncio.Queue] = None,
        sandbox_id: Optional[str] = "",
    ) -> AgentContext:
        """
        创建代理上下文对象

        Args:
            stream_mode: 是否启用流式输出
            streams: 可选的通信流实例
            agent_type: 代理类型，用于从 agent 文件中提取模型名称
            llm: 大语言模型名称
            task_id: 任务ID，若为None则自动生成
            is_main_agent: 标记当前agent是否是主agent，默认为False

        Returns:
            AgentContext: 代理上下文对象
        """
        agent_context = AgentContext()
        agent_context.set_task_id(task_id)
        agent_context.set_llm(llm)
        agent_context.stream_mode = stream_mode
        agent_context.ensure_workspace_dir()
        agent_context.is_main_agent = is_main_agent
        agent_context.set_sandbox_id(sandbox_id)

        if interrupt_queue:
            agent_context.set_interrupt_queue(interrupt_queue)

        for stream in streams:
            agent_context.add_stream(stream)

        # 如果提供了 agent_type，从文件中提取 llm
        if agent_type:
            # 读取 agent 文件内容
            agent_file = self.get_agent_file(agent_type)
            if os.path.exists(agent_file):
                try:
                    with open(agent_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    # 使用正则表达式直接从内容中提取模型名称
                    model_pattern = r"<!--\s*llm:\s*([a-zA-Z0-9-_.]+)\s*-->"
                    match = re.search(model_pattern, content, re.IGNORECASE)

                    if match:
                        model_name = match.group(1).strip()
                        agent_context.llm = model_name
                        logger.info(f"从 {agent_type}.agent 文件提取模型名称并设置为: {model_name}")
                except Exception as e:
                    logger.error(f"从 agent 文件提取 llm 时出错: {e}")

        return agent_context

    def get_agent_file(self, agent_type: str) -> str:
        """
        获取智能体文件路径
        """
        return os.path.join(PathManager.get_project_root(), "agents", f"{agent_type}.agent")

    async def _process_attachments(self, agent_context: AgentContext, query: str, attachments: List[Dict[str, Any]]) -> str:
        """
        处理附件并将其集成到查询中

        Args:
            query: 原始用户查询
            attachments: 附件列表，每个附件是一个字典，包含附件信息

        Returns:
            str: 添加了附件路径信息的查询
        """
        if not attachments:
            logger.info("消息中没有附件，返回原始查询")
            return query

        logger.info(f"收到带附件的消息，附件数量: {len(attachments)}")
        logger.info(f"消息内容: {query[:100]}{'...' if len(query) > 100 else ''}")
        logger.info(f"附件详情: {json.dumps([{k: v for k, v in a.items()} for a in attachments], ensure_ascii=False)}")

        # 初始化附件服务
        logger.info("初始化附件下载服务")
        attachment_service = AttachmentService(agent_context)

        # 下载附件
        logger.info("开始下载附件...")
        attachment_paths = await attachment_service.download_attachments(attachments)

        # 如果有成功下载的附件，将路径添加到提示中
        if attachment_paths:
            logger.info(f"成功下载 {len(attachment_paths)} 个附件")
            # 为每个附件生成路径信息
            attachment_info = "\n\n以下是用户上传的附件路径:\n"
            for i, path in enumerate(attachment_paths, 1):
                attachment_info += f"{i}. {path}\n"
                logger.info(f"附件 {i}: {path}")

            # 将附件信息添加到提示中
            message_with_attachments = f"{query}\n{attachment_info}"
            logger.info(f"将附件路径信息添加到消息中，新消息长度: {len(message_with_attachments)}")

            return message_with_attachments
        else:
            logger.info("没有成功下载的附件，返回原始查询")
            return query

"""
文件存储监听器服务，用于监听文件事件并上传文件到对象存储服务
"""

import hashlib
import json
import os
import shutil
import tempfile
import time
import traceback
from pathlib import Path
from typing import List, Optional, Union

from agentlang.context.tool_context import ToolContext
from agentlang.event.data import AfterMainAgentRunEventData
from agentlang.event.event import Event, EventType
from agentlang.logger import get_logger
from app.core.context.agent_context import AgentContext
from app.core.entity.attachment import Attachment, AttachmentTag
from app.core.entity.event.file_event import FileEventData  # 从业务层导入 FileEventData
from app.core.entity.project_archive import ProjectArchiveInfo
from app.infrastructure.storage.base import BaseFileProcessor
from app.infrastructure.storage.exceptions import InitException, UploadException
from app.infrastructure.storage.factory import StorageFactory
from app.infrastructure.storage.types import StorageResponse
from app.paths import PathManager
from app.service.agent_event.base_listener_service import BaseListenerService

logger = get_logger(__name__)


class FileStorageListenerService:
    """
    文件存储监听器服务，用于监听文件事件并将文件上传到对象存储服务
    """

    @staticmethod
    def register_standard_listeners(agent_context: AgentContext) -> None:
        """
        为代理上下文注册文件事件监听器

        Args:
            agent_context: 代理上下文对象
        """
        # 创建事件类型到处理函数的映射
        event_listeners = {
            EventType.FILE_CREATED: FileStorageListenerService._handle_file_event,
            EventType.FILE_UPDATED: FileStorageListenerService._handle_file_event,
            EventType.FILE_DELETED: FileStorageListenerService._handle_file_deleted,
            EventType.AFTER_MAIN_AGENT_RUN: FileStorageListenerService._handle_after_main_agent_run
        }

        # 使用基类方法批量注册监听器
        BaseListenerService.register_listeners(agent_context, event_listeners)

        logger.info("已为代理上下文注册文件事件和主代理完成事件监听器")

    @staticmethod
    async def _handle_file_event(event: Event[FileEventData]) -> None:
        """
        处理文件事件（创建和更新）

        Args:
            event: 文件事件对象，包含FileEventData数据
        """
        event_type_name = "创建" if event.event_type == EventType.FILE_CREATED else "更新"
        logger.info(f"处理文件{event_type_name}事件: {event.data.filepath}")

        # 1. 先上传文件到存储服务
        storage_response = await FileStorageListenerService._upload_file_to_storage(
            event.data.filepath,
            event.data.tool_context.get_extension_typed("agent_context", AgentContext)
        )

        # 2. 如果上传成功并返回了响应，创建附件并添加到事件上下文
        if storage_response:
            try:
                # 创建附件对象，传递整个StorageResponse对象
                attachment = FileStorageListenerService._create_attachment_from_uploaded_file(
                    filepath=event.data.filepath,
                    response=storage_response,
                    file_event_data=event.data
                )

                # 将附件添加到事件上下文
                FileStorageListenerService._add_attachment_to_event_context(event.data.tool_context, attachment)
                # 将附件添加到代理上下文
                FileStorageListenerService._add_attachment_to_agent_context(event.data.tool_context.get_extension_typed("agent_context", AgentContext), attachment)
            except Exception as e:
                logger.error(f"处理附件信息失败: {e}")

    @staticmethod
    async def _handle_file_deleted(event: Event[FileEventData]) -> None:
        """
        处理文件删除事件

        Args:
            event: 文件删除事件对象，包含FileEventData数据
        """
        logger.info(f"处理文件删除事件: {event.data.filepath}")
        # 文件已被删除，所以不需要上传
        # 根据业务需求，可以在这里实现删除存储服务上的文件的逻辑
        pass

    @staticmethod
    async def _handle_after_main_agent_run(event: Event[AfterMainAgentRunEventData]) -> None:
        """
        处理主代理完成事件，压缩并上传项目目录

        Args:
            event: 主代理完成事件对象，包含 AfterMainAgentRunEventData 数据
        """
        pass

    @staticmethod
    def _get_current_version() -> int:
        """
        获取当前项目压缩包的版本号

        Returns:
            int: 当前版本号，如果文件不存在则返回0
        """
        try:
            project_archive_info_file = PathManager.get_project_archive_info_file()
            if os.path.exists(project_archive_info_file):
                with open(project_archive_info_file, 'r') as f:
                    info = json.load(f)
                    return info.get('version', 0)
            return 0
        except Exception as e:
            logger.error(f"获取当前版本号时出错: {e}")
            return 0

    @staticmethod
    async def _save_and_upload_project_archive_info(
        project_archive_info: ProjectArchiveInfo,
        agent_context: AgentContext
    ) -> Optional[StorageResponse]:
        """
        保存项目存档信息到本地文件并上传到OSS

        Args:
            project_archive_info: 项目存档信息对象
            agent_context: 代理上下文对象

        Returns:
            Optional[StorageResponse]: 上传响应，失败则为None
        """
        # 持久化项目存档信息到本地文件
        project_archive_info_file = PathManager.get_project_archive_info_file()
        with open(project_archive_info_file, 'w') as f:
            json.dump(project_archive_info.model_dump(), f)
            logger.info(f"项目存档信息已保存到本地: {project_archive_info_file}")

        # 从agent_context获取storage_service
        metadata = agent_context.get_init_client_message_metadata()
        sts_token_refresh = agent_context.get_init_client_message_sts_token_refresh()

        storage_service = await StorageFactory.get_storage(
            sts_token_refresh=sts_token_refresh,
            metadata=metadata
        )

        # 上传项目存档信息文件到OSS
        project_archive_info_file_relative_path = PathManager.get_project_archive_info_file_relative_path()
        info_file_key = BaseFileProcessor.combine_path(storage_service.credentials.get_dir(), project_archive_info_file_relative_path)
        info_response = await storage_service.upload(
            file=str(project_archive_info_file),
            key=info_file_key,
            options={}
        )

        if info_response:
            logger.info(f"项目存档信息文件已上传: {info_file_key}")
        else:
            logger.error("项目存档信息文件上传失败")

        return info_response

    @staticmethod
    async def _archive_and_upload_project(agent_context: AgentContext) -> None:
        """
        压缩并上传项目目录

        Args:
            agent_context: 代理上下文对象
        """
        # 将 .chat_history 和 .workspace 目录压缩到一个压缩包中
        chat_history_dir = PathManager.get_chat_history_dir()
        workspace_dir = PathManager.get_workspace_dir()
        project_archive_dir_name = PathManager.get_project_archive_dir_name()

        combined_zip = FileStorageListenerService._compress_directory(
            directory_paths=[str(chat_history_dir), str(workspace_dir)],
            output_filename=project_archive_dir_name
        )

        if not combined_zip:
            logger.error("压缩目录失败，无法上传")
            return

        # 计算文件MD5值和大小
        file_size = os.path.getsize(combined_zip)

        # 计算文件MD5值
        md5_hash = hashlib.md5()
        with open(combined_zip, "rb") as f:
            # 分块读取文件以处理大文件
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        file_md5 = md5_hash.hexdigest()

        metadata = agent_context.get_init_client_message_metadata()
        sts_token_refresh = agent_context.get_init_client_message_sts_token_refresh()

        storage_service = await StorageFactory.get_storage(
            sts_token_refresh=sts_token_refresh,
            metadata=metadata
        )

        # 准备文件key，使用storage_service.credentials.get_dir()获取目录
        file_key = BaseFileProcessor.combine_path(storage_service.credentials.get_dir(), project_archive_dir_name + ".zip")

        # 上传合并的压缩文件
        try:
            storage_response = await storage_service.upload(
                file=combined_zip,
                key=file_key,
                options={}
            )

            if not storage_response:
                logger.error(f"上传 {project_archive_dir_name} 失败")
                return

            logger.info(f"上传 {project_archive_dir_name} 成功")

            # 获取当前版本号并递增
            current_version = FileStorageListenerService._get_current_version()
            new_version = current_version + 1
            logger.info(f"项目压缩包版本号从 {current_version} 递增到 {new_version}")

            # 创建带有递增版本号的项目存档信息
            project_archive_info = ProjectArchiveInfo(
                file_key=storage_response.key,
                file_size=file_size,
                file_md5=file_md5,
                version=new_version
            )

            # 保存项目存档信息到本地文件并上传到OSS
            await FileStorageListenerService._save_and_upload_project_archive_info(
                project_archive_info=project_archive_info,
                agent_context=agent_context
            )

            # 保存项目存档信息到代理上下文
            agent_context.set_project_archive_info(project_archive_info)

            logger.info(f"项目压缩包信息已保存: key={storage_response.key}, size={file_size}, md5={file_md5}, version={new_version}")
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"上传 {project_archive_dir_name} 时发生错误: {e}")

        # 清理临时文件
        if combined_zip and os.path.exists(combined_zip):
            try:
                os.remove(combined_zip)
                logger.info(f"已删除临时压缩文件: {combined_zip}")
            except Exception as e:
                logger.error(f"删除临时压缩文件失败: {e}")

    @staticmethod
    async def _upload_file_to_storage(filepath: str, agent_context: AgentContext) -> Optional[StorageResponse]:
        """
        将文件上传到存储服务

        Args:
            filepath: 文件路径
            agent_context: 代理上下文对象

        Returns:
            Optional[StorageResponse]: 上传成功后的存储响应对象，上传失败则返回None
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(filepath):
                logger.warning(f"文件不存在，无法上传: {filepath}")
                return None

            sts_token_refresh = agent_context.get_init_client_message_sts_token_refresh()
            metadata = agent_context.get_init_client_message_metadata()

            storage_service = await StorageFactory.get_storage(
                sts_token_refresh=sts_token_refresh,
                metadata=metadata
            )

            # 获取文件名作为存储键
            workspace_dir = agent_context.get_workspace_dir()
            # 去除掉workspace_dir - 确保两个参数都是字符串类型
            if isinstance(filepath, Path):
                filepath = str(filepath)
            if isinstance(workspace_dir, Path):
                workspace_dir = str(workspace_dir)
            file_key = filepath.replace(workspace_dir, "")
            # 设置可选项，如进度回调
            options = {}

            # 上传文件
            file_key = BaseFileProcessor.combine_path(storage_service.credentials.get_dir(), file_key)
            logger.info(f"开始上传文件: {filepath}, 存储键: {file_key}")

            response = await storage_service.upload(
                file=filepath,
                key=file_key,
                options=options
            )

            logger.info(f"文件上传成功: {filepath}, 存储键: {response.key}")
            return response

        except (InitException, UploadException) as e:
            logger.error(f"文件上传失败: {e}")
            return None
        except Exception as e:
            logger.error(f"处理文件事件过程中发生错误: {e}")
            return None

    @staticmethod
    def _create_attachment_from_uploaded_file(filepath: str, response: StorageResponse, file_event_data: FileEventData) -> Attachment:
        """
        根据上传的文件信息创建附件对象

        Args:
            filepath: 原始文件路径
            response: 存储服务上传响应，包含文件key和可能的url
            event_type: 事件类型，可选

        Returns:
            Attachment: 创建的附件对象
        """
        # 获取文件信息
        file_path_obj = Path(filepath)
        file_size = os.path.getsize(filepath)
        file_ext = file_path_obj.suffix.lstrip('.')
        file_name = file_path_obj.name
        display_name = file_name

        # 设置附件类型固定为中间产物
        if file_event_data.is_screenshot:
            file_tag = AttachmentTag.BROWSER
        else:
            file_tag = AttachmentTag.PROCESS

        # 从响应中获取file_key和可能的file_url
        file_key = response.key
        file_url = response.url  # 如果存储服务没有提供URL，这将是None

        # 创建附件对象
        attachment = Attachment(
            file_key=file_key,
            file_tag=file_tag,
            file_extension=file_ext,
            filename=file_name,
            display_filename=display_name,
            file_size=file_size,
            file_url=file_url,  # 设置文件URL，可能为None
            timestamp=int(time.time())
        )

        logger.info(f"已创建附件对象: {file_name}, 标签: {file_tag}, URL: {file_url or '无'}")
        return attachment

    @staticmethod
    def _add_attachment_to_event_context(tool_context: ToolContext, attachment: Attachment) -> None:
        """
        将附件添加到事件上下文

        Args:
            tool_context: 工具上下文
            attachment: 附件对象
        """
        try:
            # 直接使用已注册的EventContext
            from app.core.entity.event.event_context import EventContext
            event_context = tool_context.get_extension_typed("event_context", EventContext)
            if event_context:
                event_context.add_attachment(attachment)
                logger.info(f"已将文件 {attachment.filename} 作为附件添加到事件上下文")
            else:
                logger.warning("无法添加附件到事件上下文：EventContext未注册")
        except Exception as e:
            logger.error(f"添加附件到事件上下文失败: {e}")

    @staticmethod
    def _add_attachment_to_agent_context(agent_context: AgentContext, attachment: Attachment) -> None:
        """
        将附件添加到代理上下文
        """
        agent_context.add_attachment(attachment)

    @staticmethod
    def _compress_directory(directory_paths: Union[str, List[str]], output_filename: str) -> Optional[str]:
        """
        压缩指定目录，支持单个或多个目录

        Args:
            directory_paths: 要压缩的目录路径，可以是单个字符串或路径列表
            output_filename: 输出的压缩文件名（不含扩展名）

        Returns:
            Optional[str]: 成功则返回压缩文件的完整路径，失败则返回 None
        """
        try:
            # 将单个目录路径转换为列表以统一处理
            if isinstance(directory_paths, str):
                directories = [directory_paths]
            else:
                directories = directory_paths

            # 如果只有一个目录，使用原有的直接压缩逻辑（更高效）
            if len(directories) == 1 and os.path.exists(directories[0]) and os.path.isdir(directories[0]):
                directory_path = directories[0]
                # 创建临时目录以存放压缩文件
                tmp_dir = tempfile.mkdtemp()
                base_name = os.path.join(tmp_dir, output_filename)

                # 创建 .zip 格式的压缩文件
                compressed_file = shutil.make_archive(
                    base_name=base_name,  # 压缩文件的基本名称（不含扩展名）
                    format='zip',         # 压缩格式，这里使用 zip
                    root_dir=os.path.dirname(directory_path),  # 根目录（包含要压缩的目录的父目录）
                    base_dir=os.path.basename(directory_path)  # 要压缩的目录名称
                )

                logger.info(f"成功压缩目录 {directory_path} 到 {compressed_file}")
                return compressed_file

            # 多个目录的情况，需要先复制到临时目录再压缩
            # 创建临时目录作为压缩源
            temp_source_dir = tempfile.mkdtemp()

            # 复制所有有效目录到临时目录中
            valid_dirs = False
            for directory in directories:
                if not os.path.exists(directory) or not os.path.isdir(directory):
                    logger.warning(f"要压缩的目录不存在: {directory}")
                    continue

                valid_dirs = True
                dir_name = os.path.basename(directory)
                target_dir = os.path.join(temp_source_dir, dir_name)
                shutil.copytree(directory, target_dir)

            if not valid_dirs:
                logger.error("没有有效的目录可供压缩")
                shutil.rmtree(temp_source_dir)
                return None

            # 创建临时目录以存放压缩文件
            tmp_dir = tempfile.mkdtemp()
            base_name = os.path.join(tmp_dir, output_filename)

            # 创建 .zip 格式的压缩文件
            compressed_file = shutil.make_archive(
                base_name=base_name,  # 压缩文件的基本名称（不含扩展名）
                format='zip',         # 压缩格式，这里使用 zip
                root_dir=temp_source_dir,  # 根目录
                base_dir='.'          # 压缩临时目录中的所有内容
            )

            # 清理临时源目录
            shutil.rmtree(temp_source_dir)

            logger.info(f"成功将多个目录压缩到 {compressed_file}")
            return compressed_file
        except Exception as e:
            logger.error(f"压缩目录过程中发生错误: {e}")
            return None

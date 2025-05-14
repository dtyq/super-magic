"""
VolcEngine TOS upload implementation.
"""

import asyncio
import io
import time
from typing import BinaryIO, Optional

import aiohttp
from loguru import logger
from tos import TosClientV2

from .base import AbstractStorage, BaseFileProcessor, with_refreshed_credentials
from .exceptions import (
    DownloadException,
    DownloadExceptionCode,
    InitException,
    InitExceptionCode,
    UploadException,
    UploadExceptionCode,
)
from .types import BaseStorageCredentials, FileContent, Options, PlatformType, StorageResponse, VolcEngineCredentials


class VolcEngineUploader(AbstractStorage, BaseFileProcessor):
    """VolcEngine TOS uploader implementation."""

    def set_credentials(self, credentials: BaseStorageCredentials):
        """设置存储凭证"""
        if not isinstance(credentials, VolcEngineCredentials):
            if isinstance(credentials, dict):
                try:
                    credentials = VolcEngineCredentials(**credentials)
                except Exception as e:
                    raise ValueError(f"无效的凭证格式: {e}")
            else:
                raise ValueError(f"期望VolcEngineCredentials类型，得到{type(credentials)}")
        self.credentials = credentials

    def _should_refresh_credentials_impl(self) -> bool:
        """检查是否应该刷新凭证的特定逻辑"""
        if not self.credentials:
            return True

        credentials: VolcEngineCredentials = self.credentials
        if credentials.expire is None:
            return False

        # 提前180秒刷新
        return time.time() > credentials.expire - 180

    async def _refresh_credentials_impl(self):
        """执行刷新凭证操作"""
        logger.info("开始获取火山引擎STS Token")

        # 前提条件检查已经在 _should_refresh_credentials 中完成
        json_data = {}
        if self.metadata:
            json_data["metadata"] = self.metadata

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=self.sts_refresh_config.method,
                url=self.sts_refresh_config.url,
                headers=self.sts_refresh_config.headers,
                json=json_data
            ) as response:
                response.raise_for_status()
                responseBody = await response.json()
                self.credentials = VolcEngineCredentials(**responseBody["data"])
                logger.info("火山引擎STS Token获取成功")

    @with_refreshed_credentials
    async def upload(
        self,
        file: FileContent,
        key: str,
        options: Optional[Options] = None
    ) -> StorageResponse:
        """
        异步使用TOS SDK上传文件到火山引擎对象存储。
        
        Args:
            file: 文件对象，文件路径或文件内容
            key: 文件名/路径
            options: 可选配置，包括headers和progress回调
        
        Returns:
            StorageResponse: 标准化的响应对象
        
        Raises:
            InitException: 如果必要参数缺失或文件过大
            UploadException: 如果上传失败（凭证过期或网络问题）
            ValueError: 如果文件类型不支持或凭证类型错误或未设置元数据
        """
        # 此时凭证已经由装饰器刷新过，直接使用self.credentials
        if options is None:
            options = {}

        # 处理文件
        try:
            file_obj, file_size = self.process_file(file)

            # 文件大小限制检查
            if file_size > 5 * 1024 * 1024 * 1024:  # 5GB
                if isinstance(file, str):
                    file_obj.close()
                raise InitException(
                    InitExceptionCode.FILE_TOO_LARGE,
                    "volcEngine",
                    file_name=key
                )

            # 获取凭证信息
            credentials: VolcEngineCredentials = self.credentials
            tc = credentials.temporary_credential

            # 创建TOS客户端
            tos_client = TosClientV2(
                endpoint=tc.endpoint,
                region=tc.region,
                ak=tc.credentials.AccessKeyId,
                sk=tc.credentials.SecretAccessKey,
                security_token=tc.credentials.SessionToken
            )

            try:
                # 使用异步方式执行上传操作
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: tos_client.put_object(
                        bucket=tc.bucket,
                        key=key,
                        content=file_obj
                    )
                )

                # 关闭文件（如果是我们打开的）
                if isinstance(file, str):
                    file_obj.close()

                # 获取响应头
                headers = {}
                if hasattr(result, 'headers'):
                    headers = dict(result.headers)
                elif hasattr(result, 'request_info') and hasattr(result.request_info, 'headers'):
                    headers = dict(result.request_info.headers)

                # 返回标准响应
                return StorageResponse(
                    key=key,
                    platform=PlatformType.tos,
                    headers=headers
                )

            except Exception as e:
                logger.error(f"TOS error during async upload: {e}")
                if isinstance(file, str):
                    file_obj.close()
                raise UploadException(UploadExceptionCode.NETWORK_ERROR, str(e))

        except Exception as e:
            # 确保文件被关闭
            if 'file_obj' in locals() and isinstance(file, str):
                try:
                    file_obj.close()
                except:
                    pass

            if not isinstance(e, (InitException, UploadException)):
                logger.error(f"Unexpected error during async upload: {e}")
                raise UploadException(UploadExceptionCode.NETWORK_ERROR, str(e))
            raise

    @with_refreshed_credentials
    async def download(
        self,
        key: str,
        options: Optional[Options] = None
    ) -> BinaryIO:
        """
        异步从火山引擎对象存储下载文件。

        Args:
            key: 文件名/路径
            options: 可选配置

        Returns:
            BinaryIO: 文件内容的二进制流

        Raises:
            DownloadException: 如果下载失败
            ValueError: 如果凭证类型不正确或未设置元数据
        """
        # 此时凭证已经由装饰器刷新过，直接使用self.credentials

        if options is None:
            options = {}

        try:
            # 获取凭证信息
            credentials: VolcEngineCredentials = self.credentials
            tc = credentials.temporary_credential

            # 创建TOS客户端
            tos_client = TosClientV2(
                endpoint=tc.endpoint,
                region=tc.region,
                ak=tc.credentials.AccessKeyId,
                sk=tc.credentials.SecretAccessKey,
                security_token=tc.credentials.SessionToken
            )

            try:
                # 异步获取对象
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: tos_client.get_object(
                        bucket=tc.bucket,
                        key=key
                    )
                )

                # 读取内容到内存
                content = result.read()
                # 创建内存流
                file_stream = io.BytesIO(content)
                return file_stream

            except Exception as e:
                logger.error(f"Error during async download: {e}")
                raise DownloadException(DownloadExceptionCode.NETWORK_ERROR, str(e))

        except Exception as e:
            if not isinstance(e, DownloadException):
                logger.error(f"Unexpected error during async download: {e}")
                raise DownloadException(DownloadExceptionCode.NETWORK_ERROR, str(e))
            raise

    @with_refreshed_credentials
    async def exists(
        self,
        key: str,
        options: Optional[Options] = None
    ) -> bool:
        """
        异步检查存储平台上是否存在指定的文件。

        Args:
            key: 文件名/路径
            options: 可选配置

        Returns:
            bool: 如果文件存在则为True，否则为False

        Raises:
            InitException: 如果初始化参数缺失
            ValueError: 如果凭证类型错误或未设置元数据
        """
        credentials: VolcEngineCredentials = self.credentials
        if credentials is None:
            raise ValueError("未设置凭证")

        if options is None:
            options = {}

        try:
            # 获取凭证信息
            tc = credentials.temporary_credential

            # 创建TOS客户端
            tos_client = TosClientV2(
                endpoint=tc.endpoint,
                region=tc.region,
                ak=tc.credentials.AccessKeyId,
                sk=tc.credentials.SecretAccessKey,
                security_token=tc.credentials.SessionToken
            )

            try:
                # 异步检查对象是否存在
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: tos_client.head_object(
                        bucket=tc.bucket,
                        key=key
                    )
                )
                return True
            except Exception as e:
                # 对象不存在
                return False

        except Exception as e:
            logger.error(f"Error checking file existence: {e}")
            return False 

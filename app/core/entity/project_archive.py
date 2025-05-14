import time

from pydantic import BaseModel, Field


class ProjectArchiveInfo(BaseModel):
    """项目压缩包信息模型"""
    file_key: str  # 文件存储键
    file_size: int  # 文件大小（字节）
    file_md5: str  # 文件的MD5值
    upload_timestamp: int = Field(default_factory=lambda: int(time.time()))  # 上传时间戳 
    version: int = 0

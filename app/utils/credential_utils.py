"""
凭证管理工具模块，处理凭证的导出和加载
"""

import json
import os
from typing import Dict, Any, Optional

from app.core.context.agent_context import AgentContext
from agentlang.logger import get_logger

logger = get_logger(__name__)

async def export_credentials(agent_context: AgentContext, file_path: str = "config/upload_credentials.json") -> bool:
    """
    将AgentContext中的上传凭证导出到文件

    Args:
        agent_context: 代理上下文对象
        file_path: 导出文件路径，默认为config/upload_credentials.json

    Returns:
        bool: 导出是否成功
    """
    try:
        # 检查是否有凭证
        credentials = agent_context.storage_credentials
        if not credentials:
            logger.warning("AgentContext中没有存储凭证，无法导出")
            return False

        # 获取沙盒ID
        sandbox_id = agent_context.get_sandbox_id()
        if not sandbox_id:
            logger.warning("AgentContext中没有设置沙盒ID")

        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # 将凭证转换为字典
        if hasattr(credentials, "model_dump"):
            # 使用Pydantic的model_dump方法
            creds_dict = credentials.model_dump()
        else:
            # 尝试使用__dict__属性
            creds_dict = {k: v for k, v in credentials.__dict__.items()
                        if not k.startswith('_') and not callable(v)}

        # 创建输出结构
        output_data = {
            "upload_config": creds_dict
        }

        # 添加沙盒ID（如果有）
        if sandbox_id:
            output_data["sandbox_id"] = sandbox_id

        # 添加组织编码（如果有）
        organization_code = agent_context.get_organization_code()
        if organization_code:
            output_data["organization_code"] = organization_code

        # 写入文件
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        sandbox_info = f"沙盒ID: {sandbox_id}" if sandbox_id else "未设置沙盒ID"
        logger.info(f"已将上传凭证导出到文件: {file_path} ({sandbox_info})")
        return True

    except Exception as e:
        logger.error(f"导出上传凭证失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

async def load_credentials(file_path: str = "config/upload_credentials.json") -> Optional[Dict[str, Any]]:
    """
    从文件加载上传凭证

    Args:
        file_path: 凭证文件路径

    Returns:
        Optional[Dict[str, Any]]: 凭证数据，加载失败则返回None
    """
    try:
        if not os.path.exists(file_path):
            logger.warning(f"凭证文件不存在: {file_path}")
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            credentials_data = json.load(f)

        if not credentials_data.get("upload_config"):
            logger.error(f"凭证文件格式不正确，缺少upload_config字段: {file_path}")
            return None

        # 检查是否有沙盒ID
        if not credentials_data.get("sandbox_id"):
            logger.error(f"凭证文件缺少必需的sandbox_id字段: {file_path}")
            return None

        logger.info(f"已从文件加载上传凭证: {file_path}, 沙盒ID: {credentials_data.get('sandbox_id')}")

        result = credentials_data["upload_config"]

        # 添加sandbox_id到结果中
        result["sandbox_id"] = credentials_data["sandbox_id"]

        # 添加organization_code（如果存在）
        if "organization_code" in credentials_data:
            result["organization_code"] = credentials_data["organization_code"]

        return result

    except Exception as e:
        logger.error(f"加载上传凭证失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

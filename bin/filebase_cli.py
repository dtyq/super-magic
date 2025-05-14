#!/usr/bin/env python
"""
Filebase CLI工具 - 用于执行 filebase_search 和 filebase_read_file 操作

使用方法:
    python -m bin.filebase_cli search --query "查询内容" [--limit 10] [--sandbox "sandbox_id"]
    python -m bin.filebase_cli read --file_path "文件路径" [--query "查询内容"] [--return_all] [--sandbox "sandbox_id"]
    
    或者直接执行: 
    ./bin/filebase_cli.py search --query "查询内容" [--limit 10] [--sandbox "sandbox_id"]
    ./bin/filebase_cli.py read --file_path "文件路径" [--query "查询内容"] [--return_all] [--sandbox "sandbox_id"]

参数:
    search: 使用filebase_search功能搜索内容
      --query: 要搜索的查询内容，可以是单个查询或以逗号分隔的多个查询
      --limit: 返回结果的数量限制，默认为3
      --sandbox: 沙盒ID，默认为"default_sandbox"
      
    read: 使用filebase_read_file功能读取文件内容
      --file_path: 要读取的文件路径，必填参数
      --query: 查询内容，用于匹配部分内容，可选
      --return_all: 是否返回全部文件内容，加上此参数则返回全部内容
      --sandbox: 沙盒ID，默认为"default_sandbox"
"""

# 先导入基础Python库
import os
import sys
import json
import argparse
import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

# 设置正确的工作目录
# 获取项目根目录，使用文件所在位置的父目录
project_root = Path(__file__).resolve().parent.parent

# 添加项目根目录到 Python 路径
sys.path.append(str(project_root))

# 加载环境变量 - 在设置Python路径后导入
from dotenv import load_dotenv
load_dotenv(override=True)

# 初始化步骤 - 所有项目内模块导入都放到sys.path设置后
from app.paths import PathManager
PathManager.set_project_root(project_root)
from agentlang.context.application_context import ApplicationContext
ApplicationContext.set_path_manager(PathManager)

# 导入其他项目模块
from agentlang.context.tool_context import ToolContext
from app.core.context.agent_context import AgentContext
from app.tools.filebase_search import FilebaseSearch, FilebaseSearchParams
from app.tools.filebase_read_file import FilebaseReadFile, FilebaseReadFileParams
from filebase.filebase import Filebase
from filebase.filebase_config import FilebaseConfig
from agentlang.logger import configure_logging_intercept, get_logger, setup_logger

# 使用agentlang.logger模块的配置函数，从环境变量获取日志级别，默认为INFO
log_level = os.getenv("LOG_LEVEL", "INFO")
setup_logger(log_name="app", console_level=log_level)
configure_logging_intercept()

# 初始化日志记录器
logger = get_logger(__name__)


async def run_filebase_search(query: str, limit: int = 3, sandbox_id: str = "default_sandbox"):
    """
    执行filebase_search操作
    
    Args:
        query: 要搜索的查询内容
        limit: 返回结果的数量限制
        sandbox_id: 沙盒ID
    """
    start_time = time.time()
    logger.info(f"执行Filebase搜索，查询: '{query}'，结果限制: {limit}，沙盒ID: {sandbox_id}")
    
    try:
        # 创建agent_context
        agent_context = AgentContext()
        agent_context.set_sandbox_id(sandbox_id)
        
        # 创建tool_context
        tool_context = ToolContext(metadata=agent_context.get_metadata())
        # 注册 AgentContext 扩展
        tool_context.register_extension("agent_context", agent_context)
        
        # 创建搜索工具和参数
        search_tool = FilebaseSearch()
        search_params = FilebaseSearchParams(query=query, limit=limit)
        
        # 执行搜索
        result = await search_tool.execute(tool_context, search_params)
        
        # 计算执行时间
        execution_time = time.time() - start_time
        
        # 格式化并输出结果
        if result.ok:
            # 解析system字段中的JSON数据
            data = []
            if result.system:
                try:
                    data = json.loads(result.system)
                except json.JSONDecodeError:
                    logger.error("无法解析结果数据")
            
            # 获取友好的输出内容
            friendly_content = await search_tool.get_after_tool_call_friendly_content(
                tool_context, result, execution_time, {"query": query, "limit": limit}
            )
            
            print(f"\n{friendly_content}\n")
            
            # 打印搜索结果详情
            if isinstance(data, list) and data:
                print(f"搜索结果详情 ({len(data)} 条):")
                print("=" * 80)
                
                for i, item in enumerate(data, 1):
                    print(f"[{i}] 相似度得分: {item.get('score', 0):.4f}")
                    
                    metadata = item.get("metadata", {})
                    file_path = metadata.get("file_path", "未知路径")
                    file_name = metadata.get("file_name", "未知文件名")
                    
                    print(f"    文件: {file_path}")
                    
                    # 显示匹配文本片段的预览
                    text = item.get("text", "")
                    if text:
                        preview = text
                        print(f"    内容预览: {preview}")
                    
                    print("-" * 80)
        else:
            print(f"搜索失败: {result.content}")
    
    except Exception as e:
        logger.error(f"执行filebase_search时出错: {str(e)}", exc_info=True)
        print(f"执行搜索时出错: {str(e)}")


async def run_filebase_read_file(file_path: str, query: Optional[str] = None, 
                            return_all: bool = False, sandbox_id: str = "default_sandbox"):
    """
    执行filebase_read_file操作
    
    Args:
        file_path: 要读取的文件路径
        query: 查询内容，用于匹配部分内容
        return_all: 是否返回全部文件内容
        sandbox_id: 沙盒ID
    """
    start_time = time.time()
    
    read_mode = "全部内容" if return_all else "部分内容"
    query_info = f"，查询: '{query}'" if query and not return_all else ""
    logger.info(f"读取文件 '{file_path}' 的{read_mode}{query_info}，沙盒ID: {sandbox_id}")
    
    try:
        # 创建agent_context
        agent_context = AgentContext()
        agent_context.set_sandbox_id(sandbox_id)
        
        # 创建tool_context
        tool_context = ToolContext(metadata=agent_context.get_metadata())
        # 注册 AgentContext 扩展
        tool_context.register_extension("agent_context", agent_context)
        
        # 创建读取工具和参数
        read_tool = FilebaseReadFile()
        read_params = FilebaseReadFileParams(
            file_path=file_path,
            query=query,
            return_all=return_all
        )
        
        # 执行读取
        result = await read_tool.execute(tool_context, read_params)
        
        # 计算执行时间
        execution_time = time.time() - start_time
        
        # 格式化并输出结果
        if result.ok:
            # 解析system字段中的JSON数据
            content_info = {}
            if result.system:
                try:
                    content_info = json.loads(result.system)
                except json.JSONDecodeError:
                    logger.error("无法解析结果数据")
            
            # 获取友好的输出内容
            friendly_content = await read_tool.get_after_tool_call_friendly_content(
                tool_context, result, execution_time, 
                {"file_path": file_path, "query": query, "return_all": return_all}
            )
            
            print(f"\n{friendly_content}\n")
            
            # 输出文件内容
            if "content" in content_info:
                print("文件内容:")
                print("=" * 80)
                print(content_info["content"])
                print("=" * 80)
        else:
            print(f"读取文件失败: {result.content}")
    
    except Exception as e:
        logger.error(f"执行filebase_read_file时出错: {str(e)}", exc_info=True)
        print(f"读取文件时出错: {str(e)}")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='Filebase CLI工具')
    subparsers = parser.add_subparsers(dest='action', help='操作类型', required=True)
    
    # search 子命令
    search_parser = subparsers.add_parser('search', help='搜索内容')
    search_parser.add_argument('--query', type=str, required=True, help='要搜索的查询内容')
    search_parser.add_argument('--limit', type=int, default=3, help='返回结果的数量限制，默认为3')
    search_parser.add_argument('--sandbox', type=str, default='default_sandbox', help='沙盒ID，默认为default_sandbox')
    
    # read 子命令
    read_parser = subparsers.add_parser('read', help='读取文件内容')
    read_parser.add_argument('--file_path', type=str, required=True, help='要读取的文件路径')
    read_parser.add_argument('--query', type=str, help='查询内容，用于匹配部分内容')
    read_parser.add_argument('--return_all', action='store_true', help='是否返回全部文件内容')
    read_parser.add_argument('--sandbox', type=str, default='default_sandbox', help='沙盒ID，默认为default_sandbox')
    
    return parser.parse_args()


async def main():
    """主函数"""
    args = parse_args()
    
    if args.action == 'search':
        await run_filebase_search(args.query, args.limit, args.sandbox)
    elif args.action == 'read':
        await run_filebase_read_file(args.file_path, args.query, args.return_all, args.sandbox)
    else:
        logger.error(f"未知操作: {args.action}")
        print(f"未知操作: {args.action}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 
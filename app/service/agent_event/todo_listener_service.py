"""
待办事项文件监听器服务

用于监听todo.md文件事件，并将待办事项添加到代理上下文中
"""

import os
import re
from typing import Any, Dict, List

from agentlang.event.event import Event, EventType
from agentlang.logger import get_logger
from agentlang.utils.snowflake import Snowflake
from app.core.context.agent_context import AgentContext
from app.core.entity.event.event_context import EventContext
from app.core.entity.event.file_event import FileEventData
from app.service.agent_event.base_listener_service import BaseListenerService

logger = get_logger(__name__)


class TodoListenerService:
    """
    待办事项文件监听器服务
    
    监听todo.md文件的创建和更新事件，解析待办事项，并为每个待办事项创建雪花ID
    """

    # 单例模式的实例
    _instance = None

    # 雪花ID生成器
    _snowflake_service = None

    @classmethod
    def get_instance(cls) -> 'TodoListenerService':
        """
        获取单例实例
        
        Returns:
            TodoListenerService: 单例实例
        """
        if cls._instance is None:
            cls._instance = TodoListenerService()
        return cls._instance

    def __init__(self):
        """初始化待办事项监听器服务"""
        if self._snowflake_service is None:
            # 初始化雪花ID生成器
            TodoListenerService._snowflake_service = Snowflake.create_default()
        logger.info("待办事项监听器服务初始化完成")

    @staticmethod
    def register_standard_listeners(agent_context: AgentContext) -> None:
        """
        为代理上下文注册待办事项文件事件监听器
        
        Args:
            agent_context: 代理上下文对象
        """
        # 创建事件类型到处理函数的映射
        event_listeners = {
            EventType.FILE_CREATED: TodoListenerService._handle_file_event,
            EventType.FILE_UPDATED: TodoListenerService._handle_file_event
        }

        # 使用基类方法批量注册监听器
        BaseListenerService.register_listeners(agent_context, event_listeners)

        logger.info("已为代理上下文注册待办事项文件事件监听器")

    @staticmethod
    async def _handle_file_event(event: Event[FileEventData]) -> None:
        """
        处理文件事件（创建和更新）
        
        Args:
            event: 文件事件对象，包含FileEventData数据
        """
        # 获取文件路径和代理上下文
        filepath = event.data.filepath
        agent_context = event.data.tool_context.get_extension_typed("agent_context", AgentContext)

        # 获取事件上下文
        event_context = event.data.tool_context.get_extension_typed("event_context", EventContext)
        if not event_context:
            logger.warning("无法获取事件上下文：EventContext未注册")
            return

        # 检查文件是否为todo.md
        filename = os.path.basename(filepath)
        if filename.lower() != "todo.md":
            return

        # 记录处理文件事件
        event_type_name = "创建" if event.event_type == EventType.FILE_CREATED else "更新"
        logger.info(f"处理待办事项文件{event_type_name}事件: {filepath}")

        # 解析待办事项
        try:
            todo_items = TodoListenerService._parse_todo_file(filepath)

            event_context.steps_changed = True
            logger.info("检查到todo.md文件被更新，设置steps_changed标志为True")

            # 处理待办事项
            if todo_items:
                TodoListenerService._process_todo_items(todo_items, agent_context)
        except Exception as e:
            logger.error(f"解析待办事项文件出错: {e}")

    @staticmethod
    def _parse_todo_file(filepath: str) -> List[Dict[str, Any]]:
        """
        解析待办事项文件，提取待办事项
        
        Args:
            filepath: 文件路径
            
        Returns:
            List[Dict[str, Any]]: 待办事项列表，每个待办事项为一个字典，包含text和completed字段
        """
        if not os.path.exists(filepath):
            logger.warning(f"待办事项文件不存在: {filepath}")
            return []

        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                content = file.read()

            # 使用正则表达式匹配待办事项
            # 支持两种格式: "- [ ] 任务" 和 "- [x] 任务"
            todo_pattern = r'- \[([ xX])\] (.*?)(?=\n- \[|\n\n|$)'
            matches = re.findall(todo_pattern, content, re.DOTALL)

            todo_items = []
            for status, text in matches:
                text = text.strip()
                if text:
                    completed = status.lower() == 'x'
                    todo_items.append({
                        'text': text,
                        'completed': completed
                    })

            logger.info(f"从文件 {filepath} 中解析出 {len(todo_items)} 个待办事项")
            return todo_items
        except Exception as e:
            logger.error(f"读取或解析待办事项文件出错: {e}")
            return []

    @staticmethod
    def _process_todo_items(todo_items: List[Dict[str, Any]], agent_context: AgentContext) -> None:
        """
        处理待办事项，直接用最新的todo_items完全替换代理上下文中的待办事项
        
        Args:
            todo_items: 待办事项列表
            agent_context: 代理上下文
        """
        instance = TodoListenerService.get_instance()
        snowflake_service = TodoListenerService._snowflake_service

        # 创建新的待办事项字典
        new_todo_dict = {}

        # 为每个待办事项生成新记录，不检查是否已存在
        for item in todo_items:
            todo_text = item['text']
            completed = item['completed']

            # 为每个待办事项生成新的雪花ID
            snowflake_id = snowflake_service.get_id()
            new_todo_dict[todo_text] = {
                'id': snowflake_id,
                'completed': completed
            }
            logger.info(f"添加待办事项: {todo_text}, ID: {snowflake_id}, completed: {completed}")

        # 直接替换代理上下文中的待办事项字典
        agent_context.shared_context.update_field("todo_items", new_todo_dict)
        logger.info(f"已完全替换待办事项，共 {len(new_todo_dict)} 项") 

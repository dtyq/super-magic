import re
from pathlib import Path
from typing import Any, Dict, Tuple

# 新增：导入全局配置
from agentlang.config import config
from agentlang.logger import get_logger

logger = get_logger(__name__)


class AgentLoader:
    def __init__(self, agents_dir: Path):
        self._agents: Dict[str, Dict[str, Any]] = {}
        # 设置 agent 文件目录
        self._agents_dir = agents_dir

    def set_variables(self, prompt: str, variables: Dict[str, Any]) -> str:
        """
        设置变量

        Args:
            prompt: 提示词
            variables: 变量

        Returns:
            str: 替换变量后的提示词
        """
        pattern = r"\{\{([^}]+)\}\}"

        def replace_var(match):
            var_name = match.group(1).strip()
            if var_name not in variables:
                return f"{{{{未定义的变量: {var_name}}}}}"
            return str(variables[var_name])

        return re.sub(pattern, replace_var, prompt)

    def load_agent(self, agent_name: str, variables: Dict[str, Any] = None) -> Tuple[str, Dict[str, Any], Dict[str, Any], str]:
        """
        加载 agent 文件内容，并设置变量

        Args:
            agent_name: agent 名称
            variables: 变量，可选参数

        Returns:
            Tuple[str, Dict[str, Any], Dict[str, Any], str]: 解析后的模型ID、工具配置、属性配置、提示词
        """
        # 确保 variables 不为 None
        if variables is None:
            variables = {}

        # 检查 agent_name 是否已经加载
        if agent_name in self._agents:
            agent_data = self._agents[agent_name]
            return agent_data["model_id"], agent_data["tools_config"], agent_data["attributes_config"], agent_data["prompt"]

        # 获取 agent 文件内容
        agent_file_content = self._get_agent_file_content(agent_name)
        # 解析 agent 文件内容
        model_id, tools_config, attributes_config, prompt = self._parse_agent_file_content(agent_file_content)
        # 设置变量
        if variables:
            prompt = self.set_variables(prompt, variables)
        # 根据 agent_name 保存到 self._agents 中
        self._agents[agent_name] = {
            "model_id": model_id,
            "tools_config": tools_config,
            "attributes_config": attributes_config,
            "prompt": prompt,
        }
        return model_id, tools_config, attributes_config, prompt

    def _get_agent_file_content(self, agent_name: str) -> str:
        """
        获取 agent 文件内容

        Args:
            agent_name: agent 名称

        Returns:
            str: agent 文件内容
        """
        # 获取 agent 文件路径
        agent_file = self._agents_dir / f"{agent_name}.agent"
        # 检查 agent 文件是否存在
        if not agent_file.exists():
            raise FileNotFoundError(f"Agent 文件不存在: {agent_file}")
        # 读取 agent 文件内容
        with open(agent_file, "r", encoding="utf-8") as f:
            return f.read()

    def _parse_agent_file_content(self, agent_file_content: str) -> Tuple[str, Dict[str, Any], Dict[str, Any], str]:
        """解析 agent 文件内容

        Args:
            agent_file_content: agent 文件内容

        Returns:
            Tuple[str, Dict[str, Any], Dict[str, Any], str]: 解析后的模型ID、工具配置、属性配置、提示词
        """
        # 初始化配置
        tools_config = {}
        model_id = "" # 修改：不再是字典
        attributes_config = {}
        prompt = ""

        # 解析 tools_config
        tools_pattern = r"<!--\s*tools:\s*([\w,\s\.-]+)\s*-->"
        match = re.search(tools_pattern, agent_file_content)
        if match:
            tools_str = match.group(1).strip()
            tools = {tool.strip(): {} for tool in tools_str.split(",") if tool.strip()}
            logger.debug(f"从 agent 文件中解析到工具配置: {tools}")
            tools_config = tools
        else:
            logger.error("未在 agent 文件中找到工具配置")
            raise ValueError("未在 agent 文件中找到工具配置")

        # 解析 model_config
        model_pattern = r"<!--\s*llm:\s*([\w,\s\.-]+)\s*-->"
        match = re.search(model_pattern, agent_file_content)
        if match:
            # 提取模型名称或别名（假设只有一个）
            model_str = match.group(1).strip()
            # 解析别名
            resolved_model_id = config.resolve_model_alias(model_str)
            logger.debug(f"从 agent 文件中解析到模型标识 '{model_str}', 解析为 '{resolved_model_id}'")
            model_id = resolved_model_id # 修改：存储解析后的ID
        else:
            logger.error("未在 agent 文件中找到模型配置")
            # 考虑是否应该在此处引发错误，如果模型是必需的
            # raise ValueError("未在 agent 文件中找到模型配置")

        # 解析 attributes_config
        attributes_pattern = r"<!--\s*attributes:\s*([\w,\s\.-]+)\s*-->"
        match = re.search(attributes_pattern, agent_file_content)
        if match:
            attributes_str = match.group(1).strip()
            attributes = {attribute.strip(): True for attribute in attributes_str.split(",") if attribute.strip()}
            logger.debug(f"从 agent 文件中解析到属性配置: {attributes}")
            attributes_config = attributes
        else:
            logger.debug("未在 agent 文件中找到属性配置")

        # 解析 prompt
        prompt = re.sub(r"<!--(.*?)-->", "", agent_file_content, flags=re.DOTALL)
        prompt = prompt.strip()
        # logger.debug(f"从 agent 文件中解析到提示词: {prompt}")

        return model_id, tools_config, attributes_config, prompt

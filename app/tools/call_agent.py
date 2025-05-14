from typing import Any, Dict, List, Optional
from pathlib import Path

from pydantic import Field

from agentlang.context.tool_context import ToolContext
from agentlang.tools.tool_result import ToolResult
from agentlang.logger import get_logger
from app.tools.abstract_file_tool import AbstractFileTool
from app.tools.core import BaseToolParams, tool
from agentlang.utils.file import get_file_info

logger = get_logger(__name__)


class CallAgentParams(BaseToolParams):
    """调用智能体参数"""
    agent_name: str = Field(
        ...,
        description="要调用的智能体名称"
    )
    agent_id: str = Field(
        ...,
        description="本次任务的唯一标识，人类可读且有辨识度，不允许重复，由单词或短语组成，例如 'letsmagic-ai-background-research'"
    )
    task_background: str = Field(
        ...,
        description="用户原始需求与背景信息（充足的无损的背景信息总结），提供用户或上文中最原始的情况以及当前全局情况描述，避免产生致命的信息差，导致子Agent做出了超出要求以外的事情。你需要不厌其烦地向每个智能体解释清楚这个背景信息，确保每个智能体都能充分理解背景信息，避免产生信息差。不得少于300字。"
    )
    task_description: str = Field(
        ...,
        description="任务的描述（被调用的智能体只需要干这个事），重点是被调用的智能体所负责的高度拆解后的任务的具体描述，而非整体的任务描述，描述要足够简单精确，避免被调用的智能体做出超出要求以外的事情或耗费过多时间。不得少于 200 字。"
    )
    task_completion_standard: str = Field(
        ...,
        description="任务完成与验收标准（怎么才算干完了），需要量化，如产出一份文件名为 XXX 的精美的 HTML 文件。不得少于 100 字。"
    )
    reference_files: List[str] = Field(
        ...,
        description="参考文件路径列表，包含对任务有参考价值的文件，如 ['./webview_reports/foo.md', './webview_reports/bar.md']。这些文件将作为任务的背景资料或参考依据，确保智能体充分地理解和更好地完成任务。"
    )

@tool()
class CallAgent(AbstractFileTool[CallAgentParams]):
    """
    调用其它智能体来完成任务。
    每一次调用的目标要足够小，且足够明确，让智能体能够以最高效的方式完成任务。
    """

    def get_prompt_hint(self) -> str:
        """生成包含工具详细使用说明的XML格式提示信息"""
        hint = """<tool name="call_agent">
  <examples>
    <![CDATA[[以下是 call_agent 工具的使用示例，你需要严格参照示例来进行 call_agent 调用。]]>
    <example>
      <![CDATA[
call_agent(
  agent_name: "web-browser",  # 或其他适合执行网页浏览和文件下载任务的智能体
  agent_id: "aiga-pdf-download",
  task_background: "用户的原始需求是：「打开 https://educators.aiga.org/aiga-designer-2025/ 网站，找到并下载'AIGA Design 2025 Summary Document'中的PDF文件，然后将下载的PDF转换为Markdown格式」，已经较为明确，由于你是一名专业的网络浏览专家，擅长通过浏览器操作收集、整理和分析信息，因此我决定将这个任务全权交给你来执行，我会在你完成后检查你的完成情况，验收后交付给用户。",
  task_description: "你将全权负责用户原始需求中的大部分工作，你需要：1）使用浏览器打开 https://educators.aiga.org/aiga-designer-2025/ 网页，找到网页中的'AIGA Design 2025 Summary Document' PDF 文件下载链接，并下载PDF文件；2）将下载的PDF文件转换为Markdown格式",
  task_completion_standard: "成功下载PDF文件并转换为Markdown格式的文本文件，保留原文档的主要内容和结构",
  reference_files: []  # 无需参考文件
)
      ]]>
    </example>
    <example>
      <![CDATA[
call_agent(
  agent_name: "data-analyst",  # 数据分析智能体
  agent_id: "market-research-analysis",
  task_background: "用户是一家初创公司的市场部负责人，正在准备一个关于电动汽车市场趋势的演讲。他们已经收集了一些市场数据（存储在多个CSV和Excel文件中），你可以用 list_dir 在工作区看到它们，需要从这些数据中提取关键洞察，并生成一份详细的分析报告。用户原始需求是：「分析2020-2024年电动汽车市场的增长趋势、消费者购买行为变化、主要竞争对手市场份额，并生成一份包含数据可视化的详细报告」。我们已经初步处理了数据文件，现在需要深入分析并生成报告。",
  task_description: "你负责其中最重要的一个环节，你需要使用提供的参考文件中的数据：1）分析2020-2024年电动汽车销量增长趋势；2）识别不同消费者群体的购买行为变化；3）计算并比较主要竞争对手的市场份额演变；4）生成一份名为'ev_market_analysis.md'的详细分析报告，包含关键发现、数据图表和预测建议。",
  task_completion_standard: "成功生成一份名为'ev_market_analysis.md'的分析报告，报告必须包含：1）销量趋势分析（含至少2个图表）；2）消费者行为分析（含细分市场数据）；3）竞争对手分析（含市场份额对比）；4）未来12个月的市场预测；5）基于数据的3-5条具体营销建议。",
  reference_files: [
    "./ev_sales_data_2020_2023.csv",  # 电动汽车销售数据
    "./consumer_survey_results.xlsx",  # 消费者调查结果
    "./competitor_analysis.xlsx",  # 竞争对手分析
    "./industry_overview.md"  # 行业概述报告
  ]
)
      ]]>
    </example>
    <example>
      <![CDATA[
call_agent(
  agent_name: "web-browser",  # 首先调用网页浏览智能体
  agent_id: "conference-info-collector",
  task_background: "用户原始需求是：「打开 https://mp.weixin.qq.com/s/gYjV6gjFutI6afGcpNel6Q，帮我分析链接文章里的所有内容，形成结构清晰的文档，并进一步分析其中的每一个演讲主题与分享嘉宾的信息，并最终规划决定我应当如何更好地分配时间和在这些日程中做出选择，作为一个听众我该如何最大化我的参会价值，最终形成一个导航网站。」整个任务需要分两步完成：首先通过网页浏览收集信息，然后通过代码智能体构建导航网站。我们现在需要先完成第一步收集和分析信息。",
  task_description: "你需要负责任务的第一阶段：1）使用浏览器打开并访问 https://mp.weixin.qq.com/s/gYjV6gjFutI6afGcpNel6Q 链接；2）提取并分析页面上的所有会议内容，包括演讲主题、分享嘉宾信息、时间安排等；3）整理所有信息生成一个结构清晰的文档，文件名为'conference_analysis.md'；4）对每个演讲主题和嘉宾进行价值分析，标注出潜在的重要性和参与价值；5）基于分析提出时间分配建议，帮助用户作为听众最大化参会价值。",
  task_completion_standard: "成功生成一份名为'conference_analysis.md'的分析文档，文档必须包含：1）完整的会议概述；2）所有演讲主题和分享嘉宾的详细信息（至少包括姓名、职位、演讲主题、时间安排）；3）每个主题的价值分析；4）时间规划建议；5）听众参会价值最大化的策略。文档结构清晰，便于后续用于创建导航网站。",
  reference_files: []  # 无需参考文件，但会生成一个reference_file用于第二阶段
)

# 然后在第一阶段完成后，调用coder智能体建立导航网站
call_agent(
  agent_name: "coder",  # 代码开发智能体
  agent_id: "conference-navigator-builder",
  task_background: "用户原始需求是「打开 https://mp.weixin.qq.com/s/gYjV6gjFutI6afGcpNel6Q，帮我分析链接文章里的所有内容，形成结构清晰的文档，并进一步分析其中的每一个演讲主题与分享嘉宾的信息，并最终规划决定我应当如何更好地分配时间和在这些日程中做出选择，作为一个听众我该如何最大化我的参会价值，最终形成一个导航网站。」。第一阶段我们已经通过完成了会议信息的收集和分析，生成了'conference_info.md'、'conference_schedule.md'、'speakers_info.md' 几份文档，你可以在工作区的 .webview_reports 目录下查看，现在需要基于这个文档创建一个导航网站，帮助用户更好地规划会议参与。",
  task_description: "你需要负责任务的最终阶段，也是最重要的环节：1）阅读第一阶段生成的文档，理解会议的全部结构和内容；2）根据你丰富的开发设计经验与预设要求，开发一个导航网站；3）网站应帮助用户更好地规划会议参与，实现用户最大化参会价值的目标；4）包含会议总览、日程安排、嘉宾信息、主题分类、个人推荐路线等关键内容；5）提供合理的交互功能，帮助用户做出参会选择和时间分配决策。",
  task_completion_standard: "成功生成一个入口文件为'index.html'的导航网站，网站需满足以下标准：1）设计美观，采用现代UI框架；2）完整展示会议所有信息；3）必须包含四个功能模块：会议总览、日程安排、嘉宾信息和个人推荐路线；4）实现时间冲突检测和个性化推荐功能；5）提供筛选和搜索功能，方便用户快速定位感兴趣的主题和嘉宾；6）响应式设计，支持移动设备访问；7）生成PDF导出功能，方便用户离线查看；8）包含简洁的操作指南，确保可在任何浏览器环境下直接打开使用。最后的重点是避免项目过于复杂，你需要用最简单高效的组合方式尽快完成这个任务。",
  reference_files: [
    "./webview_reports/conference_info.md",  # 会议总体信息文档
    "./webview_reports/conference_schedule.md",  # 会议日程安排文档
    "./webview_reports/speakers_info.md"  # 演讲嘉宾信息文档
  ]
)
      ]]>
    </example>
    <example>
      <![CDATA[
# 第一步：使用web-browser智能体收集AI新闻热点，提取关键词
call_agent(
  agent_name: "web-browser",
  agent_id: "ai-news-collector",
  task_background: "用户原始需求是：「你可以通过 https://ai-bot.cn/daily-ai-news/ 看下近几天的热点 AI 新闻，但里面内容不详细，因此你可以从新闻标题里获取各个热点事件的搜索关键词（事件或新事物的名词提炼要精准），然后选几个你认为最有价值的事件，去微信公众号搜索与这个事件有关的文章，然后取其中你认为最有价值的几篇文章的链接，再通过浏览器去访问微信文章链接拿到文章完整 Markdown 内容，再去搜索引擎搜索这个事件有关的 36 氪、虎嗅等媒体的报道文章，然后深入理解这些文章内容，了解最近 AI 圈都在发生什么，最终回答一个终极问题「在 Cursor、Manus、Genspark、Devin 和其他各种 Agent 产品卷得要死的当下，创业团队做企业级 AI 产品，还有什么机会？」，最后将你独特的观点输出成一份报告，呈现形式为精美的网页。」这是一个复杂的多阶段任务，我们需要先收集信息，再分析观点，最后制作网页。现在需要先完成第一阶段的信息收集工作。",
  task_description: "你需要完成第一阶段的核心任务：1）访问 https://ai-bot.cn/daily-ai-news/ 网站，查看最近几天的AI新闻热点；2）从新闻标题中提取1~3个最有价值、最有影响力的热点事件关键词，关键词应该准确代表事件或新技术名称；3）对每个关键词进行简要说明，解释为什么选择这个热点；4）将你的发现整理成一个名为'ai_news_hotspots.md'的文档，这将作为后续深入研究的基础；5）记录每个热点事件在哪些平台（如微信公众号、36氪、虎嗅等）上可能有详细报道。",
  task_completion_standard: "成功生成一份名为'ai_news_hotspots.md'的热点事件分析文档，文档必须包含：1）5-8个最有价值的AI热点事件关键词；2）每个关键词的简要背景说明（为什么重要/有影响力）；3）每个关键词的推荐搜索平台（如特定的微信公众号、媒体网站等）；4）对每个热点的初步价值评估（对AI行业发展的意义）。关键词提炼必须精准，能够用于后续的深入搜索。",
  reference_files: []  # 无需参考文件
)

# 第二步：使用web-browser智能体深入研究选定的热点事件（这步可能需要多次调用，每次针对不同的热点事件）
call_agent(
  agent_name: "web-browser",
  agent_id: "ai-news-researcher",
  task_background: "用户原始需求是「你可以通过 https://ai-bot.cn/daily-ai-news/ 看下近几天的热点 AI 新闻，但里面内容不详细，因此你可以从新闻标题里获取各个热点事件的搜索关键词（事件或新事物的名词提炼要精准），然后选几个你认为最有价值的事件，去微信公众号搜索与这个事件有关的文章，然后取其中你认为最有价值的几篇文章的链接，再通过浏览器去访问微信文章链接拿到文章完整 Markdown 内容，再去搜索引擎搜索这个事件有关的 36 氪、虎嗅等媒体的报道文章，然后深入理解这些文章内容，了解最近 AI 圈都在发生什么，最终回答一个终极问题「在 Cursor、Manus、Genspark、Devin 和其他各种 Agent 产品卷得要死的当下，创业团队做企业级 AI 产品，还有什么机会？」，最后将你独特的观点输出成一份报告，呈现形式为精美的网页。」。我们已经在第一阶段识别了几个重要的AI热点事件和关键词，现在需要对这些热点进行深入研究，收集详细内容。",
  task_description: "你需要针对上一阶段识别的热点事件进行深入研究：1）查看'ai_news_hotspots.md'文件，选择其中1个最有价值的热点事件；2）针对选定的热点，在微信公众号上搜索至少3篇高质量相关文章，访问并获取其完整Markdown内容；3）同时在36氪、虎嗅等科技媒体上搜索每个热点的相关报道，由于这是新热点，可能媒体上没有报道，如果没有可以跳过；4）将所有收集到的文章内容返回给用户。",
  task_completion_standard: "成功为选定的热点事件收集详细的信息，文档必须包含：1）至少2篇微信公众号文章的完整内容；2）至少2篇来自36氪、虎嗅等媒体的报道内容（如有）；3）所有内容必须保持原始结构和格式；4）不需要进行价值分析，仅负责信息收集；5）所有收集到的文件路径都一并返回给我。",
  reference_files: [
    "./ai_news_hotspots.md"  # 第一阶段生成的热点事件文档
  ]
)

# 第三步：使用writer智能体分析所有收集的信息，回答关于AI创业机会的核心问题
call_agent(
  agent_name: "writer",
  agent_id: "ai-industry-analyst",
  task_background: "用户原始需求最终要回答「你可以通过 https://ai-bot.cn/daily-ai-news/ 看下近几天的热点 AI 新闻，但里面内容不详细，因此你可以从新闻标题里获取各个热点事件的搜索关键词（事件或新事物的名词提炼要精准），然后选几个你认为最有价值的事件，去微信公众号搜索与这个事件有关的文章，然后取其中你认为最有价值的几篇文章的链接，再通过浏览器去访问微信文章链接拿到文章完整 Markdown 内容，再去搜索引擎搜索这个事件有关的 36 氪、虎嗅等媒体的报道文章，然后深入理解这些文章内容，了解最近 AI 圈都在发生什么，最终回答一个终极问题「在 Cursor、Manus、Genspark、Devin 和其他各种 Agent 产品卷得要死的当下，创业团队做企业级 AI 产品，还有什么机会？」，最后将你独特的观点输出成一份报告，呈现形式为精美的网页。」。我们已经完成了两个阶段的工作：1）收集了最近的AI热点事件；2）收集了与热点有关的详细的行业报道和分析文章。现在需要基于这些信息，分析企业级AI产品的创业机会。",
  task_description: "你需要扮演AI产业分析师的角色，完成最核心的分析文章编写工作，输出你独一无二的观点：1）阅读所有hotspot_*.md文件和ai_news_hotspots.md文件，全面了解最近AI领域的重要动态；2）特别关注与Cursor、Manus、Genspark、Devin等Agent产品相关的信息；3）分析当前企业级AI产品的市场格局、技术趋势、用户需求和竞争态势；4）找出尚未被充分满足的企业需求和市场空白；5）提出3-5个有潜力的企业级AI产品创业方向，论证其可行性和差异化优势；6）将你的分析和见解整理成一份名为'ai_enterprise_opportunities.md'的深度报告。",
  task_completion_standard: "成功生成一份名为'ai_enterprise_opportunities.md'的高质量分析报告，报告必须包含：1）当前AI产业，特别是Agent类产品的发展现状概述；2）企业级AI市场的需求分析和痛点识别；3）至少3个具体的企业级AI产品创业机会方向，每个方向需包含：市场定位、核心价值主张、技术可行性分析、竞争优势分析、潜在风险评估；4）针对每个方向的具体落地建议；5）报告语言要专业、逻辑严密，观点要有独创性和前瞻性；6）报告结构清晰，便于后续转化为网页形式。确保报告既有行业洞察，又有实用价值，能够真正指导创业决策。",
  reference_files: [
    "./ai_news_hotspots.md",  # 热点事件总览
    "./hotspot_ai_agents.md",  # AI代理产品发展趋势分析
    "./hotspot_llm_advances.md",  # 大语言模型最新技术突破
    "./hotspot_enterprise_ai.md"   # 企业级AI应用市场动态
  ]
)

# 第四步：使用coder智能体将分析报告转化为精美网页
call_agent(
  agent_name: "coder",
  agent_id: "ai-report-visualizer",
  task_background: "用户原始需求是「你可以通过 https://ai-bot.cn/daily-ai-news/ 看下近几天的热点 AI 新闻，但里面内容不详细，因此你可以从新闻标题里获取各个热点事件的搜索关键词（事件或新事物的名词提炼要精准），然后选几个你认为最有价值的事件，去微信公众号搜索与这个事件有关的文章，然后取其中你认为最有价值的几篇文章的链接，再通过浏览器去访问微信文章链接拿到文章完整 Markdown 内容，再去搜索引擎搜索这个事件有关的 36 氪、虎嗅等媒体的报道文章，然后深入理解这些文章内容，了解最近 AI 圈都在发生什么，最终回答一个终极问题「在 Cursor、Manus、Genspark、Devin 和其他各种 Agent 产品卷得要死的当下，创业团队做企业级 AI 产品，还有什么机会？」，最后将你独特的观点输出成一份报告，呈现形式为精美的网页。」。我们已经完成了前三个阶段的工作：1）收集AI热点事件；2）深入研究重要热点；3）分析企业级AI产品的创业机会并生成了深度报告。现在需要将报告转化为视觉吸引力强、信息展示清晰的网页。",
  task_description: "你需要负责最终网页的交付阶段，是至关重要的最后一环，你需要：1）阅读'ai_enterprise_opportunities.md'分析报告(其余的 Markdown 参考文件是过程中收集到的信息，必要时可以查看)，理解其核心结构和内容；2）设计并开发一个现代、专业的单页网站，突出展示报告中的核心观点和创业机会；3）网站应包含吸引人的数据可视化元素，如趋势图表、市场机会热力图等；4）确保网站有良好的内容层级和导航结构，便于阅读长篇分析内容；5）为报告中提到的每个创业机会方向创建单独的展示区域，突出其核心价值主张和差异化优势；6）添加适当的交互元素，提升用户体验。",
  task_completion_standard: "成功开发一个入口文件为'index.html'的精美网站，网站必须满足以下标准：1）设计专业、现代，符合科技行业分析报告的风格；2）完整准确地展示报告的所有核心内容；3）包含至少3个数据可视化图表，直观展示市场趋势或机会；4）结构清晰，有明确的导航和内容分区；5）在不同屏幕尺寸下都能良好展示（响应式设计）；6）加载速度快，不依赖复杂外部资源；7）视觉设计吸引人，色彩搭配专业；8）代码结构清晰，注释完善；9）能够在任何现代浏览器中正常运行。确保网站既美观又实用，能够有效传达报告的核心价值。不要虚构参考文件以外的内容，只有参考文件里的内容才是权威可信的信息。",
  reference_files: [
    "./ai_enterprise_opportunities.md",  # 主要分析报告
    "./ai_news_hotspots.md",  # 热点事件总览
    "./hotspot_ai_agents.md",  # AI代理产品发展趋势分析
    "./hotspot_llm_advances.md",  # 大语言模型最新技术突破
    "./hotspot_enterprise_ai.md"   # 企业级AI应用市场动态
  ]
)
      ]]>
    </example>
  </examples>
</tool>"""

        return hint

    async def execute(self, tool_context: ToolContext, params: CallAgentParams) -> ToolResult:
        """
        执行代理调用

        Args:
            tool_context: 工具上下文
            params: 参数对象，包含代理名称和任务描述

        Returns:
            ToolResult: 包含操作结果
        """
        try:
            # 根据 agent_name 实例化 Agent
            from app.core.context.agent_context import AgentContext
            from app.magic.agent import Agent
            new_agent_context = AgentContext()
            agent = Agent(params.agent_name, agent_id=params.agent_id, agent_context=new_agent_context)

            # 调用 agent 的 run 方法
            query_content = f"背景信息（充足的无损的背景信息总结）: {params.task_background}\n任务描述（你所负责的内容，你只需要干这个事）: {params.task_description}\n任务完成标准（怎么样才算干完了）: {params.task_completion_standard}"

            # 添加参考文件列表及元信息
            if params.reference_files and len(params.reference_files) > 0:
                query_content += "\n\n参考文件列表："
                for file_path in params.reference_files:
                    file_info = get_file_info(file_path)
                    query_content += f"\n- {file_info}"

            result = await agent.run(query_content)

            # 确保result是字符串类型
            if result is None:
                result = f"智能体 {params.agent_name} 执行成功，但没有返回结果"
            elif not isinstance(result, str):
                result = str(result)

            return ToolResult(content=result)

        except Exception as e:
            logger.exception(f"调用智能体失败: {e!s}")
            return ToolResult(error=f"调用智能体失败: {e!s}")

    async def get_before_tool_call_friendly_content(self, tool_context: ToolContext, arguments: Dict[str, Any] = None) -> str:
        """
        获取工具调用前的友好内容
        """
        return ""

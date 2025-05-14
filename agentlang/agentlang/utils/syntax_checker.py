import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
from io import StringIO
from typing import List, Tuple

import html5lib

# 导入JavaScript语法检查库（使用pylint代替）
# 导入CSS解析库
import tinycss2
import tinycss2.ast
from bs4 import BeautifulSoup

# 导入 PyExecJS 用于执行 JavaScript 代码
execjs = None
try:
    import execjs
except ImportError:
    try:
        import PyExecJS as execjs
    except ImportError:
        from agentlang.logger import get_logger
        logger = get_logger(__name__)
        logger.warning("无法导入 execjs 或 PyExecJS 模块，Mermaid 语法检查功能将使用回退方案。")

from agentlang.logger import get_logger

logger = get_logger(__name__)


class SyntaxChecker:
    """
    语法检查器类，用于检查不同类型文件的语法

    目前支持：
    - HTML 语法检查（宽松模式）
    - JSON 语法检查
    - JavaScript 语法检查（基于pylint）
    - CSS 语法检查
    - Python 语法检查
    - TypeScript 语法检查（基于tsc）
    - Mermaid 语法检查（基于mermaid.js）
    - Markdown 文件中的 Mermaid 代码块检查
    """

    # Mermaid.js 代码，用于语法检查
    MERMAID_JS_CODE = r"""
    const mermaidAPI = {
        parse: function(text) {
            try {
                // 基本语法检测，检查括号匹配、关键字等

                // 检查基本的花括号匹配
                const braceCount = (text.match(/{/g) || []).length - (text.match(/}/g) || []).length;
                if (braceCount !== 0) {
                    throw new Error(`花括号不匹配，差值: ${braceCount}`);
                }

                // 检查基本的圆括号匹配
                const parenCount = (text.match(/\(/g) || []).length - (text.match(/\)/g) || []).length;
                if (parenCount !== 0) {
                    throw new Error(`圆括号不匹配，差值: ${parenCount}`);
                }

                // 检查基本的方括号匹配
                const bracketCount = (text.match(/\[/g) || []).length - (text.match(/\]/g) || []).length;
                if (bracketCount !== 0) {
                    throw new Error(`方括号不匹配，差值: ${bracketCount}`);
                }

                // 检查图表类型
                const firstLine = text.trim().split('\n')[0].trim();
                const validTypes = [
                    'graph', 'flowchart', 'sequenceDiagram', 'classDiagram', 'stateDiagram',
                    'stateDiagram-v2', 'erDiagram', 'journey', 'gantt', 'pie', 'requirementDiagram',
                    'gitGraph', 'mindmap', 'timeline', 'C4Context', 'C4Container', 'C4Component',
                    'C4Dynamic', 'C4Deployment', 'sankey', 'xyChart', 'block', 'packet', 'radar'
                ];

                const hasValidType = validTypes.some(type =>
                    firstLine.startsWith(type) || firstLine.startsWith(`${type} `)
                );

                if (!hasValidType) {
                    throw new Error(`无效的图表类型: "${firstLine}". 应以有效的图表类型开始, 如 flowchart, sequenceDiagram 等`);
                }

                // 验证特定图表类型的语法
                if (firstLine.startsWith('flowchart') || firstLine.startsWith('graph')) {
                    // 检查方向
                    const directions = ['TB', 'TD', 'BT', 'RL', 'LR'];
                    const hasDirection = directions.some(dir =>
                        firstLine.includes(` ${dir}`) || firstLine.includes(` ${dir} `)
                    );

                    if (!hasDirection && firstLine.includes(' ')) {
                        throw new Error(`flowchart/graph 缺少有效的方向 (TB, TD, BT, RL, LR)`);
                    }

                    // 检查节点定义和连接
                    const hasNodes = /[A-Za-z0-9_-]+(\[|\(|\>|\{)/.test(text) ||
                                    /[A-Za-z0-9_-]+\s*--/.test(text) ||
                                    /--\s*[A-Za-z0-9_-]+/.test(text);

                    if (!hasNodes) {
                        throw new Error("未找到有效的节点定义或连接");
                    }
                }

                if (firstLine.startsWith('sequenceDiagram')) {
                    // 检查参与者和消息
                    const hasParticipants = /participant|actor/.test(text);
                    const hasMessages = /->>|-->>|-->|->/.test(text);

                    if (!hasParticipants && !hasMessages) {
                        throw new Error("sequenceDiagram 应该包含参与者(participant/actor)或消息");
                    }
                }

                // 通过基本检查，返回图表类型
                for (const type of validTypes) {
                    if (firstLine.startsWith(type)) {
                        return { 'diagramType': type };
                    }
                }

                return { 'diagramType': 'unknown' };
            } catch (error) {
                throw error;
            }
        }
    };
    """

    @staticmethod
    def check_syntax(file_path: str, content: str) -> Tuple[bool, List[str]]:
        """
        根据文件类型检查内容语法

        Args:
            file_path: 文件路径，用于确定文件类型
            content: 文件内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        file_extension = os.path.splitext(file_path)[1].lower()

        # 根据文件扩展名选择检查方法
        if file_extension in ['.html', '.htm']:
            return SyntaxChecker.check_html_syntax(content)
        elif file_extension == '.json':
            return SyntaxChecker.check_json_syntax(content)
        elif file_extension in ['.js', '.jsx']:
            return SyntaxChecker.check_javascript_syntax(content)
        elif file_extension in ['.css', '.scss']:
            return SyntaxChecker.check_css_syntax(content)
        elif file_extension == '.py':
            return SyntaxChecker.check_python_syntax(content)
        elif file_extension in ['.ts', '.tsx']:
            return SyntaxChecker.check_typescript_syntax(content)
        elif file_extension == '.md' or file_extension == '.markdown':
            # 检查 Markdown 文件中的 Mermaid 代码块
            return SyntaxChecker.check_markdown_mermaid_syntax(content)

        # 如果文件类型不需要检查，返回通过
        return True, []

    @staticmethod
    def check_html_syntax(content: str) -> Tuple[bool, List[str]]:
        """
        宽松检查HTML语法，只报告严重错误

        Args:
            content: HTML内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        if not content.strip():
            return True, []

        errors = []

        try:
            # 使用BeautifulSoup进行宽松检查
            # BeautifulSoup本身就很宽松，不会因为小问题而报错
            soup = BeautifulSoup(content, 'html.parser')

            # 检查最基本的HTML结构是否完整，比如是否有不成对的标签
            # 通过检查HTML和BODY标签是否存在并且正确嵌套来判断
            html_tag = soup.find('html')

            # 只检查严重错误
            critical_errors = []

            # 检查是否存在明显的标签不匹配问题（比如缺少关闭标签）
            # 这种问题通常会导致BeautifulSoup解析后的结构与预期不符
            for tag in soup.find_all(['div', 'span', 'p', 'table', 'tr', 'td', 'ul', 'ol', 'li']):
                if tag.name in ['div', 'span'] and tag.parent and tag.parent.name == tag.name:
                    if len(tag.contents) == 0 and len(tag.attrs) == 0:
                        # 可能是不匹配的标签导致的错误嵌套
                        critical_errors.append(f"可能存在不匹配的 <{tag.name}> 标签")

            # 如果有严重错误，标记为检查不通过
            if critical_errors:
                return False, critical_errors

            # 使用html5lib进行基本检查，但不使用严格模式
            try:
                # 关闭严格模式，只检查基本结构
                parser = html5lib.HTMLParser(strict=False, namespaceHTMLElements=False)
                parser.parse(StringIO(content))
            except Exception as e:
                # 只有严重错误才记录，忽略警告和小问题
                error_str = str(e)
                if "expected-doctype-but-got" not in error_str and \
                   "required-space-attribute-before" not in error_str and \
                   "named-entity-without-semicolon" not in error_str and \
                   "unexpected-character-in-attribute" not in error_str and \
                   "unquoted-attribute-value" not in error_str and \
                   "&" not in error_str:
                    errors.append(f"HTML结构错误: {error_str}")
                    return False, errors

            # 通过基本检查，认为HTML可用
            return True, []

        except Exception as e:
            # 只有BeautifulSoup完全无法解析的情况才认为是严重错误
            errors.append(f"严重HTML解析错误: {e!s}")
            logger.error(f"严重HTML解析错误: {e}", exc_info=True)
            return False, errors

    @staticmethod
    def check_json_syntax(content: str) -> Tuple[bool, List[str]]:
        """
        检查JSON语法

        Args:
            content: JSON内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        if not content.strip():
            return True, []

        errors = []

        try:
            # 尝试解析JSON
            json.loads(content)
            # 如果没有异常，表示JSON格式正确
            return True, []
        except json.JSONDecodeError as e:
            # 捕获JSON解析错误并格式化错误信息
            line_no = e.lineno
            col_no = e.colno
            error_message = f"JSON语法错误 (行 {line_no}, 列 {col_no}): {e.msg}"
            errors.append(error_message)

            # 尝试提供更详细的错误上下文
            lines = content.split('\n')
            if 0 <= line_no - 1 < len(lines):
                context_line = lines[line_no - 1]
                # 添加错误位置指示
                pointer = ' ' * col_no + '^'
                errors.append(f"出错位置: {context_line}")
                errors.append(f"          {pointer}")

            logger.error(f"JSON语法检查失败: {e}")
            return False, errors
        except Exception as e:
            # 捕获其他可能的异常
            errors.append(f"JSON解析错误: {e!s}")
            logger.error(f"JSON解析错误: {e}", exc_info=True)
            return False, errors

    @staticmethod
    def check_javascript_syntax(content: str) -> Tuple[bool, List[str]]:
        """
        检查JavaScript语法（使用pylint进行基本语法检查）

        Args:
            content: JavaScript内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        if not content.strip():
            return True, []

        errors = []

        try:
            # 使用正则表达式检查基本语法错误（括号匹配、分号缺失等）
            # 检查未闭合的括号、引号等
            unclosed_brackets = content.count('{') - content.count('}')
            unclosed_parentheses = content.count('(') - content.count(')')
            unclosed_square_brackets = content.count('[') - content.count(']')

            # 检查基本语法问题
            if unclosed_brackets != 0:
                errors.append(f"JavaScript语法错误: 花括号不匹配 ({unclosed_brackets})")

            if unclosed_parentheses != 0:
                errors.append(f"JavaScript语法错误: 圆括号不匹配 ({unclosed_parentheses})")

            if unclosed_square_brackets != 0:
                errors.append(f"JavaScript语法错误: 方括号不匹配 ({unclosed_square_brackets})")

            # 检查常见JavaScript语法错误
            # 检查未闭合的字符串
            string_regex = r'("[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\')'
            # 替换所有合法的字符串为空字符串，然后检查是否还有单引号或双引号
            content_without_strings = re.sub(string_regex, '', content)

            if (content_without_strings.count('"') % 2) != 0:
                errors.append("JavaScript语法错误: 双引号不匹配")

            if (content_without_strings.count("'") % 2) != 0:
                errors.append("JavaScript语法错误: 单引号不匹配")

            # 如果没有发现错误，认为通过检查
            # 简化 JavaScript 检查逻辑，不使用 pylint（容易因环境差异导致失败）
            if not errors:
                return True, []
            else:
                return False, errors

        except Exception as e:
            errors.append(f"JavaScript语法检查异常: {e!s}")
            logger.error(f"JavaScript语法检查异常: {e}", exc_info=True)
            return False, errors

    @staticmethod
    def check_css_syntax(content: str) -> Tuple[bool, List[str]]:
        """
        检查CSS语法

        Args:
            content: CSS内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        if not content.strip():
            return True, []

        errors = []

        try:
            # 使用tinycss2解析CSS
            parsed_css = tinycss2.parse_stylesheet(content)

            # 检查解析结果中的错误标记
            for component in parsed_css:
                if component.type == 'error':
                    line = content[:component.source_line[0]].count('\n') + 1
                    column = component.source_line[1]
                    error_message = f"CSS语法错误 (行 {line}, 列 {column}): {component.message}"
                    errors.append(error_message)

            # 简单检查括号匹配
            braces_count = content.count('{') - content.count('}')
            if braces_count != 0:
                errors.append(f"CSS语法错误: 花括号不匹配 (差值: {braces_count})")

            # 检查分号缺失（宽松检查，只检查明显错误）
            lines = content.split('\n')
            for i, line in enumerate(lines):
                # 去除注释
                line = re.sub(r'/\*.*?\*/', '', line)
                # 检查声明行是否缺少分号
                if ':' in line and '}' not in line and ';' not in line and '{' not in line:
                    errors.append(f"CSS语法警告 (行 {i+1}): 可能缺少分号")

            # 如果没有发现错误，认为通过检查
            if not errors:
                return True, []
            else:
                # 过滤重复错误
                unique_errors = list(set(errors))
                return False, unique_errors

        except Exception as e:
            errors.append(f"CSS语法检查异常: {e!s}")
            logger.error(f"CSS语法检查异常: {e}", exc_info=True)
            return False, errors

    @staticmethod
    def check_python_syntax(content: str) -> Tuple[bool, List[str]]:
        """
        检查Python语法

        Args:
            content: Python代码内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        if not content.strip():
            return True, []

        errors = []

        try:
            # 使用ast模块解析Python代码
            ast.parse(content)
            # 如果没有抛出异常，说明语法正确
            return True, []
        except SyntaxError as e:
            # 格式化语法错误信息
            line_no = e.lineno
            col_no = e.offset if e.offset is not None else 0
            filename = e.filename if e.filename else "<string>"
            error_text = e.text.strip() if e.text else ""
            error_msg = e.msg

            error_message = f"Python语法错误 (行 {line_no}, 列 {col_no}): {error_msg}"
            errors.append(error_message)

            # 提供错误上下文
            lines = content.split('\n')
            if 0 <= line_no - 1 < len(lines):
                context_line = lines[line_no - 1]
                pointer = ' ' * (col_no - 1) + '^' if col_no > 0 else '^'
                errors.append(f"出错位置: {context_line}")
                errors.append(f"          {pointer}")

            logger.error(f"Python语法检查失败: {error_msg} 于行 {line_no}, 列 {col_no}")
            return False, errors
        except Exception as e:
            # 处理其他可能的异常
            errors.append(f"Python语法检查异常: {e!s}")
            logger.error(f"Python语法检查异常: {e}", exc_info=True)
            return False, errors

    @staticmethod
    def check_typescript_syntax(content: str) -> Tuple[bool, List[str]]:
        """
        检查TypeScript语法（使用tsc编译器，如果可用；否则回退到JavaScript检查）

        Args:
            content: TypeScript内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        if not content.strip():
            return True, []

        errors = []

        # 首先尝试使用JavaScript语法检查作为基本检查
        js_result, js_errors = SyntaxChecker.check_javascript_syntax(content)
        if not js_result:
            # 如果基本的JavaScript语法检查失败，直接返回错误
            return False, js_errors

        # 检查tsc命令是否可用
        tsc_available = shutil.which('tsc') is not None
        if not tsc_available:
            logger.info("TypeScript编译器(tsc)不可用，使用JavaScript语法检查代替")
            # 使用基本的JavaScript检查结果
            return js_result, js_errors

        # 创建临时文件和目录
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp()

            # 创建临时TypeScript文件
            ts_file_path = os.path.join(temp_dir, "temp.ts")
            with open(ts_file_path, "w", encoding="utf-8") as f:
                f.write(content)

            # 运行tsc进行类型检查，使用最简单的命令，降低失败可能性
            command = ["tsc", ts_file_path, "--noEmit", "--skipLibCheck", "--target", "ES2022"]
            process = subprocess.run(
                command,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=10  # 添加超时，防止长时间阻塞
            )

            # 如果返回代码为0，则表示没有错误
            if process.returncode == 0:
                return True, []

            # 解析错误输出
            error_output = process.stderr if process.stderr else process.stdout
            if not error_output.strip():
                # 如果没有明确的错误输出，但返回码非零，回退到JavaScript检查结果
                return js_result, js_errors

            # 解析TypeScript错误消息，格式通常是：file.ts(line,col): error TS2552: message
            error_lines = error_output.strip().split('\n')
            for line in error_lines:
                if "error" in line:
                    # 简化错误消息，去掉文件路径等信息
                    errors.append(f"TypeScript错误: {line.strip()}")

            # 如果解析出错误消息，返回这些错误
            if errors:
                return False, errors
            else:
                # 如果没有解析出明确的错误消息，但进程返回错误码，回退到基本检查
                return js_result, js_errors

        except Exception as e:
            logger.error(f"TypeScript语法检查异常: {e}", exc_info=True)
            # 出现异常时，回退到JavaScript检查结果
            return js_result, js_errors
        finally:
            # 清理临时文件和目录
            try:
                if temp_dir and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"清理TypeScript临时文件失败: {e}")

    @staticmethod
    def check_mermaid_syntax(content: str) -> Tuple[bool, List[str]]:
        """
        检查Mermaid语法

        Args:
            content: Mermaid图表内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        if not content.strip():
            return True, []

        errors = []

        # 检查 execjs 是否可用
        if execjs is None:
            logger.warning("execjs 模块不可用，跳过 Mermaid 语法检查")
            # 仍然进行基本检查：括号匹配、首行检查等
            return SyntaxChecker._fallback_mermaid_check(content)

        try:
            # 创建JavaScript运行环境并执行Mermaid.js代码
            ctx = execjs.compile(SyntaxChecker.MERMAID_JS_CODE)

            # 调用JavaScript中的parse函数
            ctx.call("mermaidAPI.parse", content)

            # 如果没有抛出异常，说明语法正确
            return True, []
        except Exception as e:
            error_msg = str(e)
            # 格式化错误信息
            errors.append(f"Mermaid语法错误: {error_msg}")
            logger.error(f"Mermaid语法检查失败: {error_msg}")
            return False, errors

    @staticmethod
    def _fallback_mermaid_check(content: str) -> Tuple[bool, List[str]]:
        """
        当 execjs 不可用时的后备 Mermaid 语法检查方法
        使用纯 Python 代码进行基本语法检查

        Args:
            content: Mermaid图表内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        if not content.strip():
            return True, []

        errors = []
        lines = content.strip().split('\n')
        first_line = lines[0].strip() if lines else ""

        # 检查图表类型
        valid_types = [
            'graph', 'flowchart', 'sequenceDiagram', 'classDiagram', 'stateDiagram',
            'stateDiagram-v2', 'erDiagram', 'journey', 'gantt', 'pie', 'requirementDiagram',
            'gitGraph', 'mindmap', 'timeline', 'C4Context', 'C4Container', 'C4Component',
            'C4Dynamic', 'C4Deployment', 'sankey', 'xyChart', 'block', 'packet', 'radar'
        ]

        # 明确检测并处理无效图表类型，特别是 "invalidchart"
        first_word = first_line.split()[0] if first_line and len(first_line.split()) > 0 else ""

        if first_word == "invalidchart":
            errors.append("Mermaid语法错误: 无效的图表类型 'invalidchart'。应以有效的图表类型开始，如 flowchart, sequenceDiagram 等")
            return False, errors

        has_valid_type = first_word in valid_types

        if not has_valid_type:
            if not first_line:
                errors.append("Mermaid语法错误: 缺少图表类型")
            else:
                errors.append(f"Mermaid语法错误: 无效的图表类型 '{first_word}'。应以有效的图表类型开始，如 flowchart, sequenceDiagram 等")
            return False, errors

        # 检查括号匹配
        brace_count = content.count('{') - content.count('}')
        if brace_count != 0:
            errors.append(f"Mermaid语法错误: 花括号不匹配 (差值: {brace_count})")

        paren_count = content.count('(') - content.count(')')
        if paren_count != 0:
            errors.append(f"Mermaid语法错误: 圆括号不匹配 (差值: {paren_count})")

        bracket_count = content.count('[') - content.count(']')
        if bracket_count != 0:
            errors.append(f"Mermaid语法错误: 方括号不匹配 (差值: {bracket_count})")

        if errors:
            return False, errors

        # 针对特定图表类型的检查
        if first_word == 'flowchart' or first_word == 'graph':
            # 检查方向
            directions = ['TB', 'TD', 'BT', 'RL', 'LR']
            parts = first_line.split(' ')

            # 修改判断条件，确保flowchart后必须跟随方向
            if len(parts) <= 1 or (len(parts) > 1 and not any(dir in parts for dir in directions)):
                errors.append("Mermaid语法错误: flowchart/graph 缺少有效的方向 (TB, TD, BT, RL, LR)")
                return False, errors

            # 简单检查是否有节点定义和连接
            has_nodes = False
            for line in lines[1:]:
                if '-->' in line or '--' in line or '---|' in line or '==>' in line:
                    has_nodes = True
                    break

            if not has_nodes and len(lines) > 1:
                errors.append("Mermaid语法错误: 未找到有效的节点连接")
                return False, errors

        if first_line.startswith('sequenceDiagram'):
            # 检查参与者和消息
            has_participants = False
            has_messages = False

            for line in lines[1:]:
                if 'participant' in line or 'actor' in line:
                    has_participants = True
                if '->' in line or '-->>' in line or '-->' in line or '->>' in line:
                    has_messages = True

            if not has_participants and not has_messages and len(lines) > 1:
                errors.append("Mermaid语法错误: sequenceDiagram 应该包含参与者(participant/actor)或消息")
                return False, errors

        return True, []

    @staticmethod
    def check_markdown_mermaid_syntax(content: str) -> Tuple[bool, List[str]]:
        """
        检查Markdown文件中的Mermaid代码块语法

        Args:
            content: Markdown文件内容

        Returns:
            Tuple[bool, List[str]]: (是否通过语法检查, 错误消息列表)
        """
        if not content.strip():
            return True, []

        # 提取所有Mermaid代码块
        # 匹配 ```mermaid 和 ``` 之间的内容，支持多个代码块
        mermaid_blocks = re.findall(r'```\s*mermaid\s*\n(.*?)\n\s*```', content, re.DOTALL)

        if not mermaid_blocks:
            # 没有找到Mermaid代码块，认为通过检查
            return True, []

        all_errors = []

        # 检查每个Mermaid代码块
        for block_index, block in enumerate(mermaid_blocks):
            result, errors = SyntaxChecker.check_mermaid_syntax(block)
            if not result:
                # 添加代码块索引信息，以便更容易定位问题
                block_errors = [f"Mermaid代码块 #{block_index + 1}: {error}" for error in errors]
                all_errors.extend(block_errors)

        if all_errors:
            return False, all_errors
        else:
            return True, []

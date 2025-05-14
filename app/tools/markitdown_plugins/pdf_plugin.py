"""PDF 解析插件实现"""

import re
from pathlib import Path
from typing import Any, BinaryIO

import PyPDF2
from markitdown import (
    DocumentConverter,
    DocumentConverterResult,
    StreamInfo,
)

__plugin_interface_version__ = 1  # 插件接口版本

ACCEPTED_MIME_TYPE_PREFIXES = [
    "application/pdf",
]

ACCEPTED_FILE_EXTENSIONS = [".pdf"]

class PDFConverter(DocumentConverter):
    """PDF 文件转换器"""

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> bool:
        """检查是否接受该文件类型"""
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        if extension in ACCEPTED_FILE_EXTENSIONS:
            return True

        for prefix in ACCEPTED_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return True

        return False

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> DocumentConverterResult:
        """转换 PDF 文件为 Markdown"""
        try:
            result_text = []

            file_name = "PDF Document"
            if hasattr(file_stream, 'name') and file_stream.name:
                file_name = Path(file_stream.name).stem

            result_text.append(f"# {file_name}")
            result_text.append("")

            # 提取元数据信息
            doc_info = []

            # 读取 PDF 文件
            pdf_reader = PyPDF2.PdfReader(file_stream)

            # 获取页数
            num_pages = len(pdf_reader.pages)
            doc_info.append(f"- 页数: {num_pages}")

            # 提取文档信息
            if pdf_reader.metadata:
                metadata = pdf_reader.metadata
                if metadata.title:
                    doc_info.append(f"- 标题: {metadata.title}")
                if metadata.author:
                    doc_info.append(f"- 作者: {metadata.author}")
                if metadata.subject:
                    doc_info.append(f"- 主题: {metadata.subject}")
                if metadata.creator:
                    doc_info.append(f"- 创建工具: {metadata.creator}")
                if hasattr(metadata, 'creation_date') and metadata.creation_date:
                    doc_info.append(f"- 创建日期: {metadata.creation_date}")

            # 添加文档信息区块
            if doc_info:
                result_text.append("## 文档信息")
                result_text.append("")
                result_text.extend(doc_info)
                result_text.append("")

            # 获取 offset 和 limit 参数
            offset = kwargs.get('offset', 0)
            limit = kwargs.get('limit', None)

            # 计算要读取的页面范围
            start_page = max(0, offset)
            end_page = num_pages if limit is None or limit <= 0 else min(num_pages, start_page + limit)

            # 如果是部分读取，添加页码范围提示
            if start_page > 0 or (end_page < num_pages and limit is not None and limit > 0):
                result_text.append(f"## 显示第 {start_page + 1} 页到第 {end_page} 页（共 {num_pages} 页）")
                result_text.append("")

            # 逐页提取内容
            for page_num in range(start_page, end_page):
                page = pdf_reader.pages[page_num]

                # 添加页码标题
                result_text.append(f"## 第 {page_num + 1} 页")

                # 提取文本
                try:
                    text = page.extract_text()
                    if text:
                        # 检测可能的表格
                        table_detected = self._detect_table(text)
                        if table_detected:
                            text = self._process_potential_table(text)

                        # 检测图片区域
                        text = self._mark_potential_images(text)

                        # 格式化文本
                        text = re.sub(r'\n{3,}', '\n\n', text)
                        text = re.sub(r'(?m)^(\s*)\*(\s+)', r'\1-\2', text)
                        text = re.sub(r'(?m)^(\s*)(\d+)\.(\s+)', r'\1\2.\3', text)
                        text = re.sub(r'(?m)^(\s*)>(\s+)', r'\1>\2', text)
                        text = self._detect_headings(text)

                        # 添加格式化后的文本
                        result_text.append(text)
                    else:
                        result_text.append("[无文本内容]")
                        result_text.append("\n*注意：此页可能为图片页面，无法提取文本内容*\n")
                except Exception as e:
                    result_text.append(f"[提取文本失败: {e!s}]")

                # 添加页面分隔符
                result_text.append("")

            # 添加前后页面提示
            if start_page > 0:
                result_text.insert(len(doc_info) + 5 if doc_info else 3, f"*注意：前 {start_page} 页未显示，可以通过设置 offset=0 查看*\n")

            if end_page < num_pages:
                result_text.append(f"*注意：还有 {num_pages - end_page} 页未显示，可以通过增加 limit 参数或调整 offset 查看*")

            return DocumentConverterResult(
                title=None,
                markdown="\n".join(result_text),
            )
        except Exception as e:
            return DocumentConverterResult(
                title=None,
                markdown=f"解析 PDF 失败: {e!s}",
            )

    def _detect_table(self, text: str) -> bool:
        """检测文本中是否包含表格"""
        lines = text.split('\n')
        if len(lines) < 3:
            return False

        space_patterns = []
        for line in lines:
            pattern = ''.join('s' if char.isspace() else 'c' for char in line)
            compressed = ''
            current = ''
            count = 0

            for char in pattern:
                if char == current:
                    count += 1
                else:
                    if current:
                        compressed += f"{current}{count}"
                    current = char
                    count = 1

            if current:
                compressed += f"{current}{count}"

            space_patterns.append(compressed)

        similar_patterns = 0
        for i in range(1, len(space_patterns)):
            if self._patterns_similar(space_patterns[i-1], space_patterns[i]):
                similar_patterns += 1
                if similar_patterns >= 2:
                    return True
            else:
                similar_patterns = 0

        return False

    def _patterns_similar(self, pattern1: str, pattern2: str) -> bool:
        """检查两个空格模式是否相似"""
        p1_spaces = pattern1.count('s')
        p2_spaces = pattern2.count('s')

        return (abs(p1_spaces - p2_spaces) / max(p1_spaces, p2_spaces, 1) < 0.3 and
                abs(len(pattern1) - len(pattern2)) / max(len(pattern1), len(pattern2), 1) < 0.3)

    def _process_potential_table(self, text: str) -> str:
        """处理可能的表格文本为 markdown 表格格式"""
        lines = text.split('\n')
        result_lines = []

        i = 0
        while i < len(lines):
            line = lines[i]

            if i + 2 < len(lines) and self._is_potential_table_row(line) and self._is_potential_table_row(lines[i+1]):
                table_lines = []
                header = line
                table_lines.append(header)

                separator = "|"
                for col in self._split_table_columns(header):
                    separator += " --- |"
                table_lines.append(separator)

                j = i + 1
                while j < len(lines) and self._is_potential_table_row(lines[j]):
                    table_lines.append(lines[j])
                    j += 1

                markdown_table = []
                for table_line in table_lines:
                    md_line = "|"
                    for col in self._split_table_columns(table_line):
                        md_line += f" {col.strip()} |"
                    markdown_table.append(md_line)

                result_lines.append("\n*检测到可能的表格内容:*\n")
                result_lines.extend(markdown_table)
                result_lines.append("\n*注意: 上述表格是基于文本分析自动生成的，可能不准确*\n")

                i = j
            else:
                result_lines.append(line)
                i += 1

        return '\n'.join(result_lines)

    def _is_potential_table_row(self, line: str) -> bool:
        """检查一行是否可能是表格的一部分"""
        if len(line.strip()) < 10:
            return False

        space_blocks = len(re.findall(r'\s{2,}', line))
        return space_blocks >= 2 and len(re.sub(r'\s+', '', line)) > 5

    def _split_table_columns(self, line: str) -> list:
        """将表格行分割为列"""
        return re.split(r'\s{2,}', line.strip())

    def _mark_potential_images(self, text: str) -> str:
        """标记可能的图片区域"""
        patterns = [
            r'图\s*\d+[\s\.:：]',
            r'figure\s*\d+[\s\.:：]',
            r'fig\.\s*\d+[\s\.:：]',
            r'image\s*\d+[\s\.:：]',
            r'photo\s*\d+[\s\.:：]',
            r'illustration\s*\d+[\s\.:：]'
        ]

        for pattern in patterns:
            text = re.sub(
                pattern=f'({pattern})(.*?)($|\n\n)',
                repl=r'\1\2\n\n*[图片占位符: 此处可能包含图片内容]*\n\3',
                string=text,
                flags=re.DOTALL | re.IGNORECASE
            )

        return text

    def _detect_headings(self, text: str) -> str:
        """检测并格式化标题"""
        lines = text.split('\n')
        result_lines = []

        for i, line in enumerate(lines):
            line_stripped = line.strip()

            if (len(line_stripped) < 60 and
                ((re.match(r'^\d+\.\s+\S+', line_stripped) and
                 (i+1 >= len(lines) or not lines[i+1].strip())) or
                (line_stripped and
                 (i+1 >= len(lines) or not lines[i+1].strip()) and
                 (i == 0 or not lines[i-1].strip())))):

                if re.match(r'^\d+\.\s+\S+', line_stripped):
                    level = len(re.match(r'^(\d+)\.', line_stripped).group(1))
                    level = min(level, 3)
                    result_lines.append('#' * level + ' ' + line_stripped)
                else:
                    result_lines.append('### ' + line_stripped)
            else:
                result_lines.append(line)

        return '\n'.join(result_lines) 

"""Excel 解析插件实现"""

from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd
from markitdown import (
    DocumentConverter,
    DocumentConverterResult,
    StreamInfo,
)

__plugin_interface_version__ = 1  # 插件接口版本

ACCEPTED_MIME_TYPE_PREFIXES = [
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
]

ACCEPTED_FILE_EXTENSIONS = [".xlsx", ".xls"]

# Excel处理的最大行数限制
EXCEL_MAX_ROWS = 1000
EXCEL_MAX_PREVIEW_ROWS = 50

class ExcelConverter(DocumentConverter):
    """Excel 文件转换器"""

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
        """转换 Excel 文件为 Markdown"""
        try:
            # 获取文件路径
            file_path = Path(file_stream.name) if hasattr(file_stream, 'name') and file_stream.name else None
            if not file_path:
                return DocumentConverterResult(
                    title=None,
                    markdown="错误: 无法获取文件路径",
                )

            # 获取 offset 和 limit 参数
            offset = kwargs.get('offset', 0)
            limit = kwargs.get('limit', None)

            # 如果未指定limit或limit<=0，则使用默认最大行数
            read_limit = EXCEL_MAX_ROWS if limit is None or limit <= 0 else limit

            # 提供pandas安装提示
            try:
                import openpyxl  # 仅用于尝试导入确认是否已安装
            except ImportError:
                return DocumentConverterResult(
                    title=None,
                    markdown="错误: 需要安装openpyxl库才能读取Excel文件: pip install openpyxl pandas",
                )

            # 获取所有工作表名称
            excel_file = pd.ExcelFile(file_path)
            sheet_names = excel_file.sheet_names

            result_text = []
            result_text.append(f"# Excel文件: {file_path.name}")
            result_text.append(f"## 包含 {len(sheet_names)} 个工作表: {', '.join(sheet_names)}\n")

            # 为每个工作表提取数据
            for sheet_name in sheet_names:
                # 读取工作表信息（行列数）
                df_info = pd.read_excel(file_path, sheet_name=sheet_name, nrows=0)
                col_count = len(df_info.columns)

                # 读取实际数据，考虑offset和limit
                df = pd.read_excel(
                    file_path,
                    sheet_name=sheet_name,
                    skiprows=offset,
                    nrows=read_limit
                )

                # 获取实际行数
                row_count = len(df)
                total_row_count = offset + row_count

                # 添加工作表信息
                result_text.append(f"## 工作表: {sheet_name}")
                result_text.append(f"* 列数: {col_count}")
                result_text.append(f"* 读取到的行数: {row_count}")

                if row_count >= read_limit:
                    result_text.append(f"* 注意: 实际行数可能超过 {read_limit} 行，此处仅显示部分数据")
                    result_text.append("* 建议: 建议使用代码处理此Excel数据，例如:")
                    result_text.append("```python")
                    result_text.append("import pandas as pd")
                    result_text.append(f"df = pd.read_excel('{file_path.name}', sheet_name='{sheet_name}')")
                    result_text.append("# 然后使用DataFrame的方法处理数据")
                    result_text.append("```")

                # 将DataFrame转为字符串表示
                if row_count > 0:
                    # 对于行数过多的情况，只显示前几行
                    if row_count > EXCEL_MAX_PREVIEW_ROWS:
                        preview_df = df.head(EXCEL_MAX_PREVIEW_ROWS)
                        result_text.append(f"\n### 数据预览 (前 {EXCEL_MAX_PREVIEW_ROWS} 行):")
                        result_text.append("```")
                        result_text.append(preview_df.to_string(index=False))
                        result_text.append("```")
                        result_text.append(f"\n* 注意: 仅显示 {EXCEL_MAX_PREVIEW_ROWS} 行数据预览，完整数据请使用代码处理")
                    else:
                        result_text.append("\n### 数据内容:")
                        result_text.append("```")
                        result_text.append(df.to_string(index=False))
                        result_text.append("```")
                else:
                    result_text.append("\n* 工作表为空或指定范围内没有数据")

                result_text.append("\n")

            return DocumentConverterResult(
                title=None,
                markdown="\n".join(result_text),
            )
        except Exception as e:
            return DocumentConverterResult(
                title=None,
                markdown=f"解析 Excel 失败: {e!s}",
            ) 

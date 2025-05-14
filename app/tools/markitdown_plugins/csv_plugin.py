"""CSV 解析插件实现"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Optional

import pandas as pd
from markitdown import (
    MarkItDown,
    DocumentConverter,
    DocumentConverterResult,
    StreamInfo,
)

__plugin_interface_version__ = 1  # 插件接口版本

ACCEPTED_MIME_TYPE_PREFIXES = [
    "text/csv",
]

ACCEPTED_FILE_EXTENSIONS = [".csv"]

# CSV处理的最大行数限制
CSV_MAX_ROWS = 1000
CSV_MAX_PREVIEW_ROWS = 50

class CSVConverter(DocumentConverter):
    """CSV 文件转换器"""

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
        """转换 CSV 文件为 Markdown"""
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
            read_limit = CSV_MAX_ROWS if limit is None or limit <= 0 else limit

            # 提供pandas安装提示
            try:
                import pandas as pd
            except ImportError:
                return DocumentConverterResult(
                    title=None,
                    markdown="错误: 需要安装pandas库才能读取CSV文件: pip install pandas",
                )

            # 尝试不同的编码读取CSV
            encodings = ['utf-8', 'gbk', 'gb2312', 'latin1']
            df = None
            used_encoding = None

            for encoding in encodings:
                try:
                    if offset > 0:
                        df = pd.read_csv(
                            file_path,
                            encoding=encoding,
                            skiprows=range(1, offset + 1),  # 保留header行，但跳过其他行
                            nrows=read_limit
                        )
                    else:
                        df = pd.read_csv(
                            file_path,
                            encoding=encoding,
                            nrows=read_limit
                        )
                    used_encoding = encoding
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    return DocumentConverterResult(
                        title=None,
                        markdown=f"使用编码 {encoding} 读取CSV失败: {str(e)}",
                    )

            if df is None:
                return DocumentConverterResult(
                    title=None,
                    markdown=f"错误: 无法用常见编码(utf-8, gbk等)读取CSV文件: {file_path.name}",
                )

            # 获取行列信息
            row_count = len(df)
            col_count = len(df.columns)

            result_text = []
            result_text.append(f"# CSV文件: {file_path.name}")
            result_text.append(f"* 使用编码: {used_encoding}")
            result_text.append(f"* 列数: {col_count}")
            result_text.append(f"* 读取到的行数: {row_count}")

            if row_count >= read_limit:
                result_text.append(f"* 注意: 实际行数可能超过 {read_limit} 行，此处仅显示部分数据")
                result_text.append("* 建议: 建议使用代码处理此CSV数据，例如:")
                result_text.append("```python")
                result_text.append("import pandas as pd")
                result_text.append(f"df = pd.read_csv('{file_path.name}', encoding='{used_encoding}')")
                result_text.append("# 然后使用DataFrame的方法处理数据")
                result_text.append("```")

            # 将DataFrame转为字符串表示
            if row_count > 0:
                # 对于行数过多的情况，只显示前几行
                if row_count > CSV_MAX_PREVIEW_ROWS:
                    preview_df = df.head(CSV_MAX_PREVIEW_ROWS)
                    result_text.append(f"\n## 数据预览 (前 {CSV_MAX_PREVIEW_ROWS} 行):")
                    result_text.append("```")
                    result_text.append(preview_df.to_string(index=False))
                    result_text.append("```")
                    result_text.append(f"\n* 注意: 仅显示 {CSV_MAX_PREVIEW_ROWS} 行数据预览，完整数据请使用代码处理")
                else:
                    result_text.append("\n## 数据内容:")
                    result_text.append("```")
                    result_text.append(df.to_string(index=False))
                    result_text.append("```")
            else:
                result_text.append("\n* CSV文件为空或指定范围内没有数据")

            return DocumentConverterResult(
                title=None,
                markdown="\n".join(result_text),
            )
        except Exception as e:
            return DocumentConverterResult(
                title=None,
                markdown=f"解析CSV失败: {str(e)}",
            ) 
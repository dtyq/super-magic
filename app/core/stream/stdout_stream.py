"""
标准输出流实现

提供基于标准输出的流实现，用于数据的读写
"""

import json
import sys
from typing import Optional

from app.core.stream import Stream
from agentlang.logger import get_logger
from agentlang.utils.json import json_dumps

logger = get_logger(__name__)


class StdoutStream(Stream):
    """A Stream implementation for handling data through standard output.
    
    This class provides a way to write string data to standard output.
    Reading is not supported and will raise an error.
    """

    def __init__(self):
        """Initialize the standard output stream."""
        super().__init__()
        self._stdout = sys.stdout

    async def read(self, size: Optional[int] = None) -> str:
        """Read is not supported for stdout streams.
        
        Args:
            size: Ignored.
            
        Raises:
            NotImplementedError: Always, as reading from stdout is not supported.
        """
        raise NotImplementedError("Reading from stdout is not supported")

    async def write(self, data: str, data_type: str = "json") -> int:
        """Write string data to the standard output using the logger.
        
        Args:
            data: The string data to be written.
            
        Returns:
            The number of bytes written.
            
        Raises:
            IOError: When there's an error writing to stdout.
        """
        try:
            if data_type == "json":
                # 格式化一下打印
                obj = json.loads(data)
                logger.info(f"StdoutStream: {json_dumps(obj, indent=2)}")
            else:
                logger.info(f"StdoutStream: {data}")
            return len(data)
        except Exception as e:
            raise IOError(f"Failed to write to stdout: {e!s}") 

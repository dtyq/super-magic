#!/usr/bin/env python3

import sys
import os
import subprocess
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

def check_matplotlib_font():
    """检查matplotlib当前使用的字体是否为WenQuanYi，如果不是则退出镜像构建"""

    # 创建一个测试文本，确认当前使用的字体
    fig, ax = plt.subplots()
    test_text = ax.text(0.5, 0.5, '测试文本', ha='center', va='center')

    # 获取文本对象的字体属性
    font_properties = test_text.get_fontproperties()
    font_name = font_properties.get_name()

    # 关闭测试图形
    plt.close(fig)

    print(f"matplotlib当前使用的字体: {font_name}")

    # 检查是否为WenQuanYi字体
    if "wqy" in font_name.lower() or "wenquanyi" in font_name.lower():
        print("✓ 当前使用的字体是WenQuanYi，符合要求")
        return True
    else:
        print("✗ 当前使用的字体不是WenQuanYi，退出镜像构建")
        sys.exit(1)  # 非零退出码会导致Docker构建失败

if __name__ == "__main__":
    print("\n检查matplotlib字体配置...")
    check_matplotlib_font()

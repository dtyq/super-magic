#!/usr/bin/env python3

import sys
import os
import subprocess
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

def create_font_config():
    """创建系统默认字体配置文件，设置WenQuanYi为首选字体"""

    font_config = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <alias>
    <family>sans-serif</family>
    <prefer>
      <family>WenQuanYi Zen Hei</family>
    </prefer>
  </alias>
  <alias>
    <family>serif</family>
    <prefer>
      <family>WenQuanYi Zen Hei</family>
    </prefer>
  </alias>
  <alias>
    <family>monospace</family>
    <prefer>
      <family>WenQuanYi Zen Hei Mono</family>
    </prefer>
  </alias>
</fontconfig>
"""

    # 检查目录是否存在，不存在则创建
    os.makedirs("/etc/fonts", exist_ok=True)

    try:
        with open("/etc/fonts/local.conf", "w") as f:
            f.write(font_config)
        print("✓ 成功创建字体配置文件: /etc/fonts/local.conf")

        # 更新字体缓存
        subprocess.run(["fc-cache", "-fv"], check=True)
        print("✓ 成功更新字体缓存")

        # 打印系统字体配置信息
        print("\n========== 系统字体配置信息 ==========")
        subprocess.run(["fc-match", "sans-serif"])
        subprocess.run(["fc-match", "serif"])
        subprocess.run(["fc-match", "monospace"])

        print("\n========== 系统安装的字体列表 ==========")
        result = subprocess.run(["fc-list"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if "wenquanyi" in line.lower() or "wqy" in line.lower():
                print(line)
    except Exception as e:
        print(f"创建字体配置文件失败: {str(e)}")
        return False

    return True

def configure_matplotlib():
    """创建并配置 matplotlib，设置 WenQuanYi 为默认字体"""
    # 创建配置目录
    os.makedirs("/root/.config/matplotlib", exist_ok=True)

    # 配置内容
    config_content = """backend: Agg
font.family: sans-serif
font.sans-serif: WenQuanYi Zen Hei, DejaVu Sans, Arial, sans-serif
axes.unicode_minus: False
"""

    # 写入配置文件
    try:
        with open("/root/.config/matplotlib/matplotlibrc", "w") as f:
            f.write(config_content)
        print("✓ 成功创建 matplotlib 配置文件")
    except Exception as e:
        print(f"创建 matplotlib 配置文件失败: {str(e)}")
        return False

    return True

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
    print("配置系统字体...")
    create_font_config()

    print("\n配置 matplotlib...")
    configure_matplotlib()

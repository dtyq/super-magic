# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

block_cipher = None

# 收集magika模块的所有Python文件和数据文件
magika_imports = collect_submodules('magika')
magika_datas = collect_data_files('magika')

a = Analysis(
    ['main.py'],
    pathex=['.'],  # 只保留当前目录，因为 -e 安装应使包可导入
    binaries=[],
    datas=[
        *magika_datas,
        # 添加您需要的数据文件，格式为 ('源文件路径', '目标目录')
        # 例如: ('config.json', '.'),
        ('agents', 'agents'),  # 添加agents目录
        ('config', 'config'),  # 添加config目录
        # 添加所有js文件
        ('magic_use/js', 'magic_use/js'),
        ('magic_use/magic_monkey', 'magic_use/magic_monkey'),
        # 添加需要被动态加载的组件包的元数据，使得 importlib.metadata.entry_points 可以发现工具包
        *copy_metadata('filebase'),
        *copy_metadata('enterprise')
    ],
    # 需要被动态加载的隐性组件包
    hiddenimports=magika_imports + [
        'tiktoken_ext.openai_public', 'tiktoken_ext',
        # 使得包可以被动态 import 进来
        'filebase.tools',
        'enterprise.tools',
        'enterprise.service.agent_event'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 这里过滤掉不需要的文件
def exclude_files(file_list):
    return [x for x in file_list if not (
        # 排除虚拟环境
        x[0].startswith('.venv') or
        x[0].startswith('venv') or
        x[0].startswith('env') or
        # 排除缓存文件
        '__pycache__' in x[0] or
        '.pyc' in x[0] or
        # 排除测试文件
        '/tests/' in x[0] or
        '/test_' in x[0] or
        # 排除git相关
        '.git/' in x[0]
    )]

# 应用过滤器
a.binaries = exclude_files(a.binaries)
a.datas = exclude_files(a.datas)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='.',  # 添加此行，使所有文件在同一目录中
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='main',
)

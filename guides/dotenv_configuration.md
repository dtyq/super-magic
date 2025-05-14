# .env 文件优先级配置

## 概述

项目中使用了 `python-dotenv` 库来加载环境变量，默认情况下，该库不会覆盖已存在的系统环境变量。本次修改使得项目能够优先从 `.env` 文件读取配置，即使同名的环境变量已经存在于系统中。

## 技术实现

通过为所有 `load_dotenv()` 调用添加 `override=True` 参数，实现了让 `.env` 文件中的配置优先级高于系统环境变量。

修改了以下文件中的 `load_dotenv()` 调用：

1. `main.py`
2. `bin/v6.py`
3. `bin/filebase_watcher.py`
4. `app/vector_store/example.py`
5. `app/vector_store/examples/collection_prefix_example.py`

## 使用方法

无需改变现有的使用方式，只需确保将需要覆盖的环境变量配置写入 `.env` 文件即可。这些配置将会覆盖系统中已存在的同名环境变量。

## 备注

- 如果需要在特定场景下恢复原来的行为（不覆盖系统环境变量），可以临时将对应 `load_dotenv()` 调用的 `override` 参数设置为 `False`。
- 该修改尤其适用于开发和测试环境，可以轻松切换不同的配置而无需修改系统环境变量。

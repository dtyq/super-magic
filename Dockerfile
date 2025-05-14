# 使用 Playwright 基础镜像
FROM ghcr.io/dtyq/super-magic-python-base-image:latest

# 设置工作目录
WORKDIR /app

# 复制并安装项目依赖
COPY requirements.txt .

# 安装依赖，使用缓存挂载优化
RUN pip install -r requirements.txt

# 安装沙箱环境依赖
COPY requirements_sandbox.txt .
RUN pip install -r requirements_sandbox.txt

# 创建matplotlib配置目录
RUN mkdir -p /root/.config/matplotlib

# 复制字体检查脚本
COPY deploy/ /app/deploy/

# 检查matplotlib字体（如果字体不是WenQuanYi，则构建失败）
RUN python /app/deploy/configure_font.py
RUN python /app/deploy/check_font.py

# 更新环境变量路径
ENV PATH="/usr/local/bin:${PATH}"

COPY . .

RUN pip install -e agentlang

# 获取Git commit ID并保存到环境变量
ARG GIT_COMMIT_ID="未知"
ENV GIT_COMMIT_ID=${GIT_COMMIT_ID}

EXPOSE 8000
EXPOSE 8002

CMD ["python3", "main.py", "start", "ws-server"]

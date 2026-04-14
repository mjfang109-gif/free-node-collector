# 微软官方 Playwright 镜像 (Ubuntu 24.04 Noble)
FROM mcr.microsoft.com/playwright/python:v1.45.0-noble

WORKDIR /app

# 安装 FFmpeg 和 中文字体
USER root
RUN apt-get update && \
    apt-get install -y ffmpeg fonts-wqy-zenhei && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 仅复制 requirements.txt 并安装 Python 依赖
# (requirements.txt 里写上: qrcode, pillow, playwright)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码通过 compose 的 volumes 挂载，这里无需 COPY 代码
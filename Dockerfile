# ============================================================
# free-node-collector 运行环境
# 只负责环境配置，代码由宿主机挂载进来
# 使用方式：
#   docker build -t node-collector .
#   docker run --rm -v $(pwd):/app node-collector
# ============================================================

FROM python:3.11-slim

# ── 系统依赖 ────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 网络工具curl 用于调试,ca-certificates 保证 TLS 正常
    curl \
    ca-certificates \
    # Go 工具链（用于编译安装 clash-speedtest）
    golang \
    && rm -rf /var/lib/apt/lists/*

# ── 安装 clash-speedtest ────────────────────────────────────
# 单独一层，利用 Docker 缓存，只要源码没变就不重新编译
ENV GOPATH=/root/go
ENV PATH=$PATH:/root/go/bin

RUN go install github.com/faceair/clash-speedtest@latest \
    # 验证安装成功,打印帮助确认可用flag
    && clash-speedtest -h 2>&1 | head -20 \
    # 清理 Go 构建缓存，减小镜像体积
    && go clean -cache -modcache

# ── Python 依赖 ─────────────────────────────────────────────
# 先单独复制 requirements.txt，利用层缓存
# 代码变化时不需要重新安装依赖
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 运行 ───────────────────────────────────────────────────
# 代码目录由宿主机挂载，这里只设置入口
# -u 禁用 Python 输出缓冲，让日志实时显示
CMD ["python", "-u", "-m", "src.main"]
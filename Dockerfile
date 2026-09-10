FROM python:3.13-slim

WORKDIR /app

# 层缓存：先装依赖（依赖变了才重新装）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再装项目代码
COPY agent ./agent
COPY pyproject.toml readme.md ./

# 生产镜像不装测试依赖，避免容器启动时加载 pytest 插件
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "agent.api:app", "--host", "0.0.0.0", "--port", "8080"]

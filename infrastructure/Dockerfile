FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY workspace/pyproject.toml workspace/README.md ./
COPY workspace/mail_core ./mail_core
COPY workspace/mcp_server ./mcp_server

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1 \
    MAIL_MCP_CONFIG=/data/config/accounts.yaml

CMD ["uvicorn", "mcp_server.http:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE /src/
COPY wallapop_mcp /src/wallapop_mcp
RUN pip install --no-cache-dir fastmcp==4.1.4 /src

COPY packaging/homelab/bridge.py packaging/homelab/healthcheck.py /app/
EXPOSE 8768
CMD ["python", "/app/bridge.py"]

FROM node:22-bookworm-slim AS supergateway
RUN npm install --global --omit=dev supergateway@4.2.2

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    WALLAPOP_CONFIG_DIR=/data
WORKDIR /app
COPY --from=supergateway /usr/local/bin/node /usr/local/bin/node
COPY --from=supergateway /usr/local/lib/node_modules/supergateway /usr/local/lib/node_modules/supergateway
RUN ln -s /usr/local/lib/node_modules/supergateway/dist/index.js /usr/local/bin/supergateway
COPY pyproject.toml README.md LICENSE /src/
COPY wallapop_mcp /src/wallapop_mcp
RUN pip install --no-cache-dir /src
EXPOSE 8768
CMD ["supergateway", "--stdio", "wallapop-mcp --allow-writes --session /data", "--outputTransport", "streamableHttp", "--stateful", "--sessionTimeout", "120000", "--host", "0.0.0.0", "--port", "8768", "--streamableHttpPath", "/mcp", "--apiKeyFile", "/run/secrets/mcptoken"]

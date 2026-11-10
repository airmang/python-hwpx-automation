# syntax=docker/dockerfile:1
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HWPX_AUTOMATION_PROFILE=full \
    HWPX_AUTOMATION_TRANSPORT=streamable-http \
    HWPX_AUTOMATION_HOST=127.0.0.1 \
    HWPX_AUTOMATION_PORT=8000 \
    HWPX_AUTOMATION_WORKSPACE_ROOTS='["/tmp/hwpx-playmcp"]'

WORKDIR /app

RUN python -m pip install --upgrade pip setuptools wheel

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src

RUN pip install ".[mcp,http]" \
    && mkdir -p /tmp/hwpx-playmcp \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app /tmp/hwpx-playmcp

USER appuser

EXPOSE 8000

# The server only listens inside the container by default. To publish the port,
# run with -e HWPX_AUTOMATION_HOST=0.0.0.0 and -e HWPX_AUTOMATION_HTTP_TOKEN=<long
# random secret>; clients then send "Authorization: Bearer <token>". Without a
# token the server refuses a non-loopback bind.
CMD ["hwpx-automation-mcp"]

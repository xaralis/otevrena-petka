# Otevřená Pětka: portal web + API + MCP (`petka serve`) and section jobs (`usneseni update`).
FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
COPY migrations ./migrations
# seed data (texts + parse/enrich results); DATA_DIR on a volume is filled from it
COPY data ./data
RUN uv sync --frozen --no-dev

USER 65534:65534
EXPOSE 8080
CMD ["usneseni", "serve", "--port", "8080"]

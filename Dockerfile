FROM python:3.11-slim-bookworm

# DuckDB named timezones (Europe/Rome) + slim image has no tzdata by default
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY notebooks ./notebooks

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
ENV DATA_DUMPS_ROOT=/data
ENV PYTHONUNBUFFERED=1

# Default: notebook (override for one-shot ingest via compose)
CMD ["marimo", "run", "notebooks/spotify.py", "--host", "0.0.0.0", "--port", "2718", "--headless", "--token"]

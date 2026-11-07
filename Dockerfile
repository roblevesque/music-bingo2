# syntax=docker/dockerfile:1
FROM python:3.12-slim

# uv installs the locked dependencies. Pin a version here for fully reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    MUSICBINGO_DATA_DIR=/data

WORKDIR /app

# Dependencies first, so rebuilding after a code change reuses this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app

# Run as an unprivileged user; /data is where the database, clips and secret key live.
RUN useradd --system --uid 10001 --home-dir /app bingo \
 && mkdir /data \
 && chown bingo:bingo /data
USER bingo
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/static/styles.css', timeout=3)"

# One worker only: live updates are held in memory.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

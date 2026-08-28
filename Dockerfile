FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm

WORKDIR /app
RUN useradd --create-home --uid 1000 lia
COPY --from=builder --chown=lia:lia /app/.venv /app/.venv
COPY --chown=lia:lia src ./src

USER lia
ENV PATH="/app/.venv/bin:$PATH" \
    DATABASE_PATH=/app/data/lia.db \
    HEARTBEAT_PATH=/app/data/heartbeat \
    BACKUP_DIR=/app/data/backups

HEALTHCHECK --interval=1m --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "\
import pathlib, sys, time; \
p = pathlib.Path('/app/data/heartbeat'); \
sys.exit(0 if p.exists() and time.time() - p.stat().st_mtime < 180 else 1)"

CMD ["python", "-m", "lia"]

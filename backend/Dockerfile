# ==============================================================================
# FlowPilot AI Backend - Containerfile
# ==============================================================================
FROM python:3.12-slim

# Install system runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy dependency specifications, lockfile, and package metadata
COPY pyproject.toml uv.lock README.md ./

# Install project dependencies into system Python
ENV UV_SYSTEM_PYTHON=1
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source and migrations
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Install the flowpilot package in editable mode without reinstalling dependencies
RUN uv pip install -e . --no-deps

# Create and switch to non-root application user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser && \
    chown -R appuser:appgroup /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src
USER appuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "flowpilot.main:app", "--host", "0.0.0.0", "--port", "8000"]

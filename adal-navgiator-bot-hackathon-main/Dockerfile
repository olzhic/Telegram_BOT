FROM python:3.11-slim

# Install system dependencies for uv and uvx, and clean up apt caches to keep the image small
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
# Install uv from the official Astral image to get the latest version of uv and uvx
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./

# Install curl permanently and clean up apt caches to keep the image small
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Use a cache mount for uv to speed up dependency installation and avoid re-downloading packages on rebuilds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

RUN useradd --create-home --uid 10001 appuser
COPY app ./app
COPY data ./data
COPY scripts ./scripts
USER appuser

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

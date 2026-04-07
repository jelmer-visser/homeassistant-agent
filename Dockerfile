# Multi-stage build — keeps the final image lean
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --no-cache-dir hatchling

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build wheel
RUN pip wheel --no-deps --wheel-dir /wheels .


# ── Final image ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Create non-root user
RUN groupadd --gid 1000 haagent && \
    useradd --uid 1000 --gid haagent --shell /bin/bash --create-home haagent

WORKDIR /app

# Install runtime deps from wheel
COPY --from=builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Directories for config and logs (will be volume-mounted)
RUN mkdir -p /app/config /app/logs && \
    chown -R haagent:haagent /app

USER haagent

# Health check — run a quick connectivity test (won't call Claude)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import asyncio; from ha_agent.config import get_settings; from ha_agent.ha.client import HAClient; s=get_settings(); asyncio.run(HAClient(s).__aenter__())" || exit 1

ENTRYPOINT ["ha-agent"]
CMD []

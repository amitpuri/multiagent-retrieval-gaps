# Production Deployment Container for Google ADK Agent Harness
# Build from the repository root:
#   docker build -f google-adk-agents/Dockerfile -t clinical-adk-harness .
FROM python:3.12-slim

# Avoid writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY google-adk-agents/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source and domain configuration from repo root
COPY google-adk-agents/src/ /app/src/
COPY config/ /app/config/
COPY google-adk-agents/pytest.ini /app/
COPY google-adk-agents/README.md /app/

# Create a non-root user for runtime (CIS Docker Benchmark L1-4.1)
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --no-create-home appuser && \
    chown -R appuser:appgroup /app

# Switch to non-root user before starting the process
USER appuser

# Expose production ASGI HTTP port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Start the Agent Harness continuous FastAPI service
CMD ["uvicorn", "src.harness.server:app", "--host", "0.0.0.0", "--port", "8000"]

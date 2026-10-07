# Production Container for AWS Strands Agents SDK & Amazon Bedrock AgentCore
# Build from the repository root:
#   docker build -f strands-agents/Dockerfile -t strands-agents .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY strands-agents/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source and domain configuration from repo root
COPY strands-agents/src/ /app/src/
COPY config/ /app/config/
COPY strands-agents/pytest.ini /app/
COPY strands-agents/README.md /app/

# Create a non-root user for runtime (CIS Docker Benchmark L1-4.1)
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --no-create-home appuser && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Start continuous FastAPI service
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]

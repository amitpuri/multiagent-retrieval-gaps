# Production Container for Microsoft Agent Framework (MAF) Clinical Agents
# Build from the repository root:
#   docker build -f agent-framework/Dockerfile -t agent-framework .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY agent-framework/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy declarative agents, workflows, source, and domain configuration
COPY agent-framework/declarative-agents/ /app/declarative-agents/
COPY agent-framework/declarative-workflows/ /app/declarative-workflows/
COPY agent-framework/src/ /app/src/
COPY config/ /app/config/
COPY agent-framework/pytest.ini /app/
COPY agent-framework/README.md /app/

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
CMD ["uvicorn", "src.harness.server:app", "--host", "0.0.0.0", "--port", "8000"]

# Production Deployment Container for Google ADK Agent Harness
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
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source and configuration
COPY src/ /app/src/
COPY pytest.ini /app/
COPY README.md /app/

# Expose production ASGI HTTP port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Start the Agent Harness continuous FastAPI service
CMD ["uvicorn", "src.harness.server:app", "--host", "0.0.0.0", "--port", "8000"]

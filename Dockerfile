FROM python:3.11-slim AS base

WORKDIR /app

# System deps for tiktoken (needs regex C extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY scripts/ scripts/

ENV PYTHONUNBUFFERED=1
ENV CONTEXTPILOT_DATA_DIR=/data

VOLUME /data
EXPOSE 8080 8400

CMD ["python", "-m", "src.web", "--host", "0.0.0.0", "--port", "8080", "--mcp-port", "8400"]

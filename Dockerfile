FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

ENV PYTHONUNBUFFERED=1
ENV CONTEXTPILOT_DATA_DIR=/data

VOLUME /data
EXPOSE 8080 8400

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/dashboard')" || exit 1

CMD ["python", "-m", "src.web", "--host", "0.0.0.0", "--port", "8080", "--mcp-port", "8400"]

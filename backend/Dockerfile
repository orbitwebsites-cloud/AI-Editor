FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY training/ /app/training/
ENV PORT=8000 \
    DATA_DIR=/app/data \
    EDITING_KNOWLEDGE_PATH=/app/training/editing_knowledge_v1.json
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/health', timeout=4)" || exit 1
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]

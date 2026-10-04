# Web UI: React + coss ui, built into call_analyzer/web/static.
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim

# INSTALL_GPU=true adds the CUDA libraries for Whisper on an NVIDIA GPU (~3 GB more; see docker-compose.gpu.yml).
ARG INSTALL_GPU=false
# INSTALL_CONVERT=true adds CPU torch + transformers, needed once to convert the Tunisian Derja Whisper models.
ARG INSTALL_CONVERT=false

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# chromium + Noto fonts: PDF export with proper Arabic text. nodejs/npm: the Claude Code CLI (CLAUDE_BACKEND=subscription).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates chromium fonts-noto-core nodejs npm \
 && npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-gpu.txt requirements-convert.txt ./
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_GPU" = "true" ]; then pip install -r requirements-gpu.txt; fi \
 && if [ "$INSTALL_CONVERT" = "true" ]; then \
      pip install -r requirements-convert.txt --extra-index-url https://download.pytorch.org/whl/cpu; fi
# Where the pip-installed CUDA libraries live (no effect when they aren't installed).
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib

RUN useradd --create-home --uid 1000 app \
 && mkdir -p /app/data /app/reports /home/app/.claude \
 && chown -R app:app /app /home/app
COPY --chown=app:app .env.example ./
COPY --chown=app:app context ./context
COPY --chown=app:app call_analyzer ./call_analyzer
COPY --chown=app:app --from=frontend /src/call_analyzer/web/static ./call_analyzer/web/static

USER app
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz')"
CMD ["python", "-m", "call_analyzer", "ui", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]

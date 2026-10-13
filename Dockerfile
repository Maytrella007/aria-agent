# =============================================================================
# Stage 1: Build SvelteKit frontend
# =============================================================================
FROM node:22-slim AS frontend-builder

WORKDIR /web

# Install dependencies first (cache layer)
COPY web/package.json web/package-lock.json ./
RUN npm ci --production=false

# Copy source and build
COPY web/ .
RUN npm run build

# =============================================================================
# Stage 2: Python runtime + built frontend
# =============================================================================
FROM python:3.12-slim AS runtime

# System dependencies for Playwright, audio, git, tmux, Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libxshmfence1 libx11-xcb1 \
    ffmpeg git tmux \
    nodejs npm \
    # Supervisor to run both FastAPI and SvelteKit
    supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

# Pre-download sentence-transformers embedding model (~90MB)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# Copy Python application
COPY aria.py config.yaml ./
COPY core/ core/
COPY scripts/ scripts/

# Copy built SvelteKit from stage 1
COPY --from=frontend-builder /web/build /app/web/build
COPY --from=frontend-builder /web/package.json /app/web/package.json
COPY --from=frontend-builder /web/node_modules /app/web/node_modules

# Supervisor config to run both processes
COPY deploy/supervisord.conf /etc/supervisor/conf.d/aria.conf

# Create non-root user
RUN groupadd -r aria && useradd -r -g aria -d /app -s /sbin/nologin aria \
    && mkdir -p data data/auth data/mirror data/conversations data/backups \
    && chown -R aria:aria /app

USER aria

# FastAPI on 8000, SvelteKit on 3000
EXPOSE 3000 8000

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/status')" || exit 1

# Supervisor manages both FastAPI and SvelteKit
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/aria.conf", "-n"]

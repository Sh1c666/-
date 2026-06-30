# syntax=docker/dockerfile:1
#
# NetPilot — single-image build.
# Stage 1 compiles the React/Vite SPA; stage 2 assembles the Python backend and
# drops the built SPA where FastAPI serves it (/). Result: one container, one
# process, open http://localhost:8000.

# ---------- Stage 1: build the frontend -------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /build

# Deps first (cached unless package*.json change).
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Build → /build/dist (tsc -b && vite build).
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: backend runtime ----------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Must bind 0.0.0.0 inside the container or the host port map can't reach it.
    NETPILOT_HOST=0.0.0.0 \
    NETPILOT_PORT=8000

# Diagnostic tools shell out to these on Linux:
#   ping → iputils-ping, traceroute → traceroute, tracepath → iputils-tracepath
# ca-certificates is needed for HTTPS / TLS probing.
RUN apt-get update && apt-get install -y --no-install-recommends \
        iputils-ping \
        traceroute \
        iputils-tracepath \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# pyproject.toml references readme = "../README.md", so place it at /app/README.md.
COPY README.md /app/README.md
COPY backend/ /app/backend/

# Editable install keeps the app's __file__-relative path resolution working
# (FRONTEND_DIST = /app/frontend/dist, data dir = /app/backend/data).
RUN pip install --no-cache-dir -e .

# Built SPA, served by FastAPI at / with SPA fallback.
COPY --from=frontend /build/dist /app/frontend/dist

# Profiles + UI settings live here; mount a named volume to persist them.
RUN mkdir -p /app/backend/data
VOLUME /app/backend/data

EXPOSE 8000
CMD ["python", "-m", "netpilot.main"]

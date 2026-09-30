# Stage 1: Build React frontend (context is repo root, so use langchain_agent/web/)
FROM node:24-slim AS frontend-builder

WORKDIR /app/web

COPY langchain_agent/web/package.json langchain_agent/web/package-lock.json* ./
RUN npm ci

COPY langchain_agent/web/ ./
# Use empty VITE_API_URL so production builds use relative URLs (same-domain requests)
RUN VITE_API_URL="" npm run build

# Stage 2: Python application
FROM python:3.14-slim AS runtime

WORKDIR /app

# Install Python dependencies (context is repo root, so prefix with langchain_agent/)
COPY langchain_agent/requirements.txt ./
# Install CPU-only torch before requirements.txt so sentence-transformers reuses it.
# This container has no GPU; the default PyPI torch wheel bundles ~2GB of CUDA
# libraries that are never used. The CPU wheel cuts the pip layer from ~3GB to ~750MB.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Bake the cross-encoder reranker model into the image (issue #78) so it is never
# fetched from HuggingFace Hub at container start. Keep this id in sync with
# core/config.py's CROSS_ENCODER_MODEL.
ENV HF_HOME=/opt/hf-cache
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-12-v2')"

# Copy application source (context is repo root, so prefix with langchain_agent/)
# NOTE: COPY *.py only matches top-level files, not directories — any new
# top-level package (like tools/) needs its own explicit COPY line here
# or it silently won't exist in the image, crashing the app at import time on
# boot (issue #18).
COPY langchain_agent/*.py ./
COPY langchain_agent/api/ ./api/
COPY langchain_agent/core/ ./core/
COPY langchain_agent/pipeline/ ./pipeline/
COPY langchain_agent/retrieval/ ./retrieval/
COPY langchain_agent/quality/ ./quality/
COPY langchain_agent/observability/ ./observability/
COPY langchain_agent/tools/ ./tools/
# scripts/ is deliberately NOT copied: those are local entry points invoked from
# the Makefile, never imported at runtime.
# tests/unit/test_dockerfile_package_copy.py enforces the rule above -- it
# fails if any package imported at runtime is missing a COPY line here.

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/web/dist ./web/dist

# Run fully offline for HuggingFace at runtime (issue #78) — the cross-encoder is
# already baked into the image above, so never attempt an HF Hub network call.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Set Python path so imports resolve from /app
ENV PYTHONPATH=/app

# Standard container convention: bind whatever PORT is passed in (default 8080)
ENV PORT=8080

EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]

# Stage 1: build the TypeScript frontend.
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime with the built frontend stapled in.
FROM python:3.13-slim
WORKDIR /app

# uv for fast, reproducible installs from pyproject.toml + uv.lock
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache .

COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist

CMD ["sh", "-c", "uvicorn serve:app --host 0.0.0.0 --port ${PORT:-8000}"]

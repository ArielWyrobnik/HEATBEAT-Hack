# HEATBEAT web app: React frontend + FastAPI backend in one container (one free web service).
# Build and run locally:  docker build -t heatbeat . && docker run -p 8000:8000 heatbeat
# Then open http://localhost:8000

# 1) Build the frontend (static files in frontend/dist)
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# 2) Python runtime with the API, the models and the committed data
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements-deploy.txt ./
RUN pip install -r requirements-deploy.txt
COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist
# Build the SQLite database from data/parquet once at image build, so the first visitor does not wait for it
RUN python -c "import heatbeat_data as hd; hd.list_sites(); print('database ready')"
# Hosts (Render, Hugging Face, Fly) pass the port in $PORT
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn heatbeat_api.app:app --host 0.0.0.0 --port ${PORT}"]

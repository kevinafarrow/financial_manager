# ---- frontend build ----
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.13-slim
RUN useradd --create-home --uid 1000 fm
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /build/dist ./frontend/dist

# main.py resolves the frontend relative to the repo layout (backend/app/../..)
# so mirror it: /app/app + /app/frontend/dist works with STATIC_DIR logic
ENV FM_DATA_DIR=/data \
    FM_BACKUP_DIR=/backups \
    FM_PORT=8000 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data /backups && chown fm:fm /data /backups /app
USER fm
EXPOSE 8000
VOLUME ["/data", "/backups"]

CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]

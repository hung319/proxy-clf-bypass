# Base image nhỏ và an toàn hơn
FROM python:3.9-slim

# Tối ưu cài đặt
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Cài đặt các package tối thiểu
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential gcc curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Cài đặt thư viện cần thiết
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf ~/.cache

COPY . .

ENV APP_PORT=5000
ENV PROXY_VERBOSE_LOGGING="false"
ENV DEV_MODE="false"

EXPOSE 5000

# Chỉ chạy 1 worker Uvicorn để tiết kiệm RAM (có thể scale bằng container nếu cần)
CMD ["/bin/sh", "-c", "exec gunicorn proxy_server:app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind \"0.0.0.0:$APP_PORT\" --log-level warning"]

FROM python:3.9-alpine

# Không tạo file bytecode + luôn hiển thị log
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Cài các dependencies cần thiết để build và chạy cloudscraper
RUN apk update && apk add --no-cache \
    build-base \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev \
    python3-dev \
    py3-pip \
    curl \
    libxml2-dev \
    libxslt-dev \
    libressl-dev \
    libjpeg-turbo-dev \
    zlib-dev \
    && rm -rf /var/cache/apk/*

# Đặt thư mục làm việc
WORKDIR /app

# Sao chép và cài đặt requirements trước để cache Docker layer
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn
COPY . .

# Biến môi trường mặc định
ENV APP_PORT=5000
ENV PROXY_VERBOSE_LOGGING="false"
ENV DEV_MODE="false"

# Mở cổng ứng dụng
EXPOSE 5000

# Chạy app bằng Gunicorn + Uvicorn Worker (1 worker nhẹ)
CMD ["/bin/sh", "-c", "exec gunicorn proxy_server:app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind \"0.0.0.0:$APP_PORT\" --timeout 60 --log-level warning"]

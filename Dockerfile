# --- Stage 1: Builder ---
# Sử dụng một image đầy đủ hơn để build các dependencies
FROM python:3.11-slim-bullseye as builder

# Thiết lập biến môi trường để pip không phàn nàn về việc chạy bằng root
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Cài đặt các thư viện cần thiết
COPY requirements.txt .
# --prefix /install giúp cô lập các gói đã cài đặt vào một thư mục riêng
RUN pip install --prefix=/install -r requirements.txt

# --- Stage 2: Final ---
# Sử dụng một base image gọn nhẹ cho môi trường chạy production
FROM python:3.11-slim-bullseye

# Tạo một user và group không phải root để chạy ứng dụng
RUN groupadd -r appuser && useradd --no-log-init -r -g appuser appuser

WORKDIR /app

# Sao chép các gói đã cài đặt từ stage builder
COPY --from=builder /install /usr/local
# Sao chép mã nguồn ứng dụng
COPY . .

# Thay đổi quyền sở hữu của thư mục ứng dụng cho user mới
RUN chown -R appuser:appuser /app

# Chuyển sang user không phải root
USER appuser

# Biến môi trường (không thay đổi)
ENV APP_PORT=5000
ENV PROXY_VERBOSE_LOGGING="false"
# ENV PROXY_API_KEY="" # Vẫn sẽ được cung cấp lúc runtime
ENV DEV_MODE="false"

# Thêm biến môi trường cho Gunicorn workers (sẽ được giải thích bên dưới)
ENV WEB_CONCURRENCY=2

# Expose port
EXPOSE 5000

# Lệnh để chạy ứng dụng. Sử dụng exec để Gunicorn trở thành tiến trình chính (PID 1)
# WEB_CONCURRENCY cho phép bạn dễ dàng điều chỉnh số lượng workers
CMD exec gunicorn proxy_server:app \
    --workers $WEB_CONCURRENCY \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:$APP_PORT" \
    --log-level info

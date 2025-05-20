# Sử dụng một base image Python gọn nhẹ
FROM python:3.9-slim

# Thiết lập thư mục làm việc bên trong container
WORKDIR /app

# Sao chép file requirements.txt trước để tận dụng Docker cache
COPY requirements.txt .

# Cài đặt các thư viện Python
# Cài đặt các dependencies hệ thống cần thiết cho Playwright trước
# Các dependencies này có thể thay đổi tùy theo phiên bản Playwright và base image
# Tham khảo: https://playwright.dev/docs/docker
# RUN apt-get update && apt-get install -y \
#     libnss3 \
#     libnspr4 \
#     libdbus-1-3 \
#     libatk1.0-0 \
#     libatk-bridge2.0-0 \
#     libcups2 \
#     libdrm2 \
#     libxkbcommon0 \
#     libatspi2.0-0 \
#     libxcomposite1 \
#     libxdamage1 \
#     libxfixes3 \
#     libxrandr2 \
#     libgbm1 \
#     libasound2 \
#     # Thêm các gói khác nếu cần thiết dựa trên thông báo lỗi khi build
#     && rm -rf /var/lib/apt/lists/* # Dòng trên có thể cần nếu base image không đủ. 
# `--with-deps` của playwright install sẽ cố gắng cài đặt chúng.

RUN pip install --no-cache-dir -r requirements.txt

# Tải về trình duyệt cho Playwright (ví dụ: chromium) và các OS dependencies của nó
# Bước này có thể tốn thời gian và làm tăng kích thước image
RUN python -m playwright install --with-deps chromium
# Hoặc chỉ `playwright install chromium` nếu bạn tự quản lý OS dependencies

# Sao chép toàn bộ mã nguồn của ứng dụng vào thư mục làm việc
COPY . .

# (Các biến môi trường ENV giữ nguyên)
ENV APP_PORT=5000
ENV PROXY_VERBOSE_LOGGING="false"
# ENV PROXY_API_KEY="" 
ENV DEV_MODE="false"

EXPOSE 5000

CMD ["/bin/sh", "-c", "exec gunicorn proxy_server:app --workers 5 --worker-class uvicorn.workers.UvicornWorker --bind \"0.0.0.0:$APP_PORT\" --log-level warning"]

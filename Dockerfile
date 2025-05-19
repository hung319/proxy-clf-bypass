# Sử dụng một base image Python gọn nhẹ
FROM python:3.9-slim

# Thiết lập thư mục làm việc bên trong container
WORKDIR /app

# Sao chép file requirements.txt trước để tận dụng Docker cache
COPY requirements.txt .

# Cài đặt các thư viện Python
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn của ứng dụng vào thư mục làm việc
COPY . .

# Biến môi trường cho port ứng dụng (Gunicorn sẽ sử dụng)
ENV APP_PORT=5000
# Biến môi trường để kiểm soát log chi tiết của ứng dụng proxy
ENV PROXY_VERBOSE_LOGGING="false"

# Expose port mà ứng dụng sẽ lắng nghe bên trong container
EXPOSE 5000

# Lệnh để chạy ứng dụng khi container khởi động
# Sử dụng Gunicorn làm WSGI server, với log level là warning
CMD ["gunicorn", "--bind", "0.0.0.0:$APP_PORT", "--workers", "2", "--log-level", "warning", "proxy_server:app"]

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

# Biến môi trường cho port ứng dụng
ENV APP_PORT=5000
# Biến môi trường để kiểm soát log chi tiết của ứng dụng proxy
ENV PROXY_VERBOSE_LOGGING="false"
# Biến môi trường cho API Key (người dùng sẽ cung cấp khi chạy container)
# ENV PROXY_API_KEY="" 
# Biến môi trường để bật chế độ reload cho Uvicorn khi chạy local (không khuyến khích cho production)
ENV DEV_MODE="false"


# Expose port mà ứng dụng sẽ lắng nghe bên trong container
EXPOSE 5000 
# Nên khớp với APP_PORT

# Lệnh để chạy ứng dụng khi container khởi động
# Sử dụng Uvicorn để chạy ứng dụng FastAPI
# --host 0.0.0.0 để lắng nghe trên tất cả các interface
# --port $APP_PORT để sử dụng port từ biến môi trường
# --workers 1 (Uvicorn thường được chạy với 1 worker process, việc scale được thực hiện bằng cách chạy nhiều container hoặc dùng Gunicorn quản lý Uvicorn workers)
# Nếu bạn muốn nhiều worker hơn với Uvicorn mà không có Gunicorn, bạn cần xem xét các tùy chọn của Uvicorn hoặc dùng process manager.
# Mặc định, Uvicorn sẽ chạy với 1 worker.
CMD ["uvicorn", "proxy_server:app", "--host", "0.0.0.0", "--port", "$APP_PORT"]

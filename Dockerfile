# Sử dụng một base image Python gọn nhẹ
FROM python:3.9-slim

# Thiết lập thư mục làm việc bên trong container
WORKDIR /app

# Sao chép file requirements.txt trước để tận dụng Docker cache
COPY requirements.txt .

# Cài đặt các thư viện Python
# --no-cache-dir để giảm kích thước image
# --trusted-host pypi.python.org --trusted-host pypi.org --trusted-host files.pythonhosted.org có thể cần nếu có vấn đề SSL/TLS khi build
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn của ứng dụng vào thư mục làm việc
COPY . .

# Biến môi trường cho port ứng dụng (Gunicorn sẽ sử dụng)
# Giá trị mặc định là 5000, có thể ghi đè lúc `docker run`
ENV APP_PORT=5000

# Các biến môi trường cho SOCKS5 proxy (người dùng sẽ cung cấp khi chạy container)
# ENV SOCKS5_PROXY_HOST=""
# ENV SOCKS5_PROXY_PORT=""
# ENV SOCKS5_USERNAME=""
# ENV SOCKS5_PASSWORD=""

# Expose port mà ứng dụng sẽ lắng nghe bên trong container
# Port này cần khớp với APP_PORT và lệnh CMD của Gunicorn
EXPOSE 5000

# Lệnh để chạy ứng dụng khi container khởi động
# Sử dụng Gunicorn làm WSGI server
# Gunicorn sẽ tìm đối tượng 'app' trong file 'proxy_server.py'
# Số lượng workers có thể được điều chỉnh (ví dụ: (2 x $CPU_CORES) + 1)
CMD ["gunicorn", "--bind", "0.0.0.0:$APP_PORT", "--workers", "2", "proxy_server:app"]

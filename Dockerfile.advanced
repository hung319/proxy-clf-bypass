FROM python:3.11-slim

# Cài đặt system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    procps \
    libxss1 \
    libgconf-2-4 \
    libxrandr2 \
    libasound2 \
    libpangocairo-1.0-0 \
    libatk1.0-0 \
    libcairo-gobject2 \
    libgtk-3-0 \
    libgdk-pixbuf2.0-0 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libnss3 \
    libcups2 \
    libxrandr2 \
    libasound2 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cài đặt Playwright
RUN python -m playwright install chromium
RUN python -m playwright install-deps

COPY . .

# Environment variables cho Turnstile bypass
ENV STEALTH_MODE=true
ENV TURNSTILE_TIMEOUT=60000
ENV MAX_TURNSTILE_RETRIES=3

EXPOSE 5000

CMD ["python", "proxy_server_advanced.py"]

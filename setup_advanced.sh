#!/bin/bash

echo "Cài đặt Advanced Proxy Server với Turnstile Bypass..."

# Cài đặt Python packages
pip install -r requirements.txt

# Cài đặt Playwright browsers
python -m playwright install chromium

# Cài đặt system dependencies
python -m playwright install-deps

# Cài đặt playwright-stealth
pip install playwright-stealth

echo "Hoàn thành cài đặt!"
echo ""
echo "Sử dụng:"
echo "  /turnstile-bypass?url=https://example.com"
echo "  /status"

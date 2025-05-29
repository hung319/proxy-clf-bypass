#!/bin/bash

echo "Cài đặt Playwright browsers..."

# Cài đặt browsers cho Playwright
python -m playwright install chromium

# Cài đặt dependencies của system
python -m playwright install-deps

echo "Hoàn thành cài đặt Playwright!"

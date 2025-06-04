from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
from typing import Optional
import os
import traceback
import asyncio
import cloudscraper
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import uvicorn

# --- Khởi tạo ứng dụng FastAPI ---
app = FastAPI(title="Cloudscraper Proxy API", version="1.0.0")

# --- Đọc cấu hình từ biến môi trường ---
SOCKS5_PROXY_HOST = os.environ.get('SOCKS5_PROXY_HOST')
SOCKS5_PROXY_PORT_STR = os.environ.get('SOCKS5_PROXY_PORT')
SOCKS5_PROXY_PORT = int(SOCKS5_PROXY_PORT_STR) if SOCKS5_PROXY_PORT_STR and SOCKS5_PROXY_PORT_STR.isdigit() else None
SOCKS5_USERNAME = os.environ.get('SOCKS5_USERNAME')
SOCKS5_PASSWORD = os.environ.get('SOCKS5_PASSWORD')

APP_LISTEN_PORT = int(os.environ.get('APP_PORT', '5000'))
PROXY_VERBOSE_STR = os.environ.get('PROXY_VERBOSE_LOGGING', 'false').lower()
PROXY_VERBOSE = PROXY_VERBOSE_STR == 'true'
EXPECTED_API_KEY = os.environ.get('PROXY_API_KEY')

# --- Tạo ThreadPoolExecutor ---
executor = ThreadPoolExecutor(max_workers=10)

# --- Hàm cấu hình proxy ---
def get_socks_proxy_settings():
    if SOCKS5_PROXY_HOST and SOCKS5_PROXY_PORT:
        proxy_url_scheme = 'socks5h'
        auth_part = ''
        if SOCKS5_USERNAME and SOCKS5_PASSWORD:
            auth_part = f'{SOCKS5_USERNAME}:{SOCKS5_PASSWORD}@'
        elif SOCKS5_USERNAME:
            auth_part = f'{SOCKS5_USERNAME}@'
        proxy_full_url = f'{proxy_url_scheme}://{auth_part}{SOCKS5_PROXY_HOST}:{SOCKS5_PROXY_PORT}'
        return {'http': proxy_full_url, 'https': proxy_full_url}
    return None

# --- Hàm đồng bộ fetch nội dung ---
def fetch_final_content_sync(target_url: str, client_referer: Optional[str] = None):
    active_proxies = get_socks_proxy_settings()
    log_prefix = f"Proxying '{target_url}'"
    if client_referer:
        log_prefix += f" (Referer: '{client_referer}')"
    print(log_prefix)

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
    )

    if active_proxies:
        scraper.proxies = active_proxies
        print(f"  SOCKS5 Proxy configured: {active_proxies.get('http')}")
    elif PROXY_VERBOSE:
        print("  No SOCKS5 Proxy configured.")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8',
            'Connection': 'keep-alive'
        }
        if client_referer:
            headers['Referer'] = client_referer

        initial_response = scraper.get(target_url, headers=headers, allow_redirects=True)
        current_url = initial_response.url
        content = initial_response.content
        content_type = initial_response.headers.get('Content-Type', 'application/octet-stream')
        status = initial_response.status_code

        return content, content_type, status, None

    except Exception as e:
        return None, None, 500, f"Error: {str(e)}\n{traceback.format_exc()}"

# --- Async wrapper ---
async def fetch_final_content_from_url(url: str, referer: Optional[str] = None):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(fetch_final_content_sync, url, referer))

# --- Route chính ---
@app.get("/", response_class=FastAPIResponse)
async def proxy_handler(
    request: Request,
    url: Optional[str] = Query(None),
    referer: Optional[str] = Query(None),
    auth_token: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    if EXPECTED_API_KEY:
        actual_key = x_api_key or auth_token
        if not actual_key:
            raise HTTPException(status_code=401, detail="Thiếu API key.")
        if actual_key != EXPECTED_API_KEY:
            raise HTTPException(status_code=403, detail="API key không hợp lệ.")

    if not url:
        raise HTTPException(status_code=400, detail="Thiếu tham số 'url'")

    content, content_type, status_code, error_msg = await fetch_final_content_from_url(url, referer)
    if error_msg and not content:
        raise HTTPException(status_code=status_code or 500, detail=error_msg)

    return FastAPIResponse(content=content, status_code=status_code or 200, media_type=content_type)

if __name__ == '__main__':
    print(f"FastAPI Proxy đang chạy tại http://0.0.0.0:{APP_LISTEN_PORT}")
    uvicorn.run("proxy_server:app", host="0.0.0.0", port=APP_LISTEN_PORT, reload=(os.environ.get("DEV_MODE", "false").lower() == "true"))

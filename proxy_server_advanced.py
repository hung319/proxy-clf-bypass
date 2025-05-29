from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
from typing import Optional
import os
import traceback
import uvicorn
import asyncio
import random
import time
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from fake_useragent import UserAgent

# Khởi tạo ứng dụng FastAPI
app = FastAPI(title="Advanced Cloudscraper Proxy API with Turnstile Bypass", version="2.0.0")

# --- Cấu hình từ biến môi trường ---
SOCKS5_PROXY_HOST = os.environ.get('SOCKS5_PROXY_HOST')
SOCKS5_PROXY_PORT_STR = os.environ.get('SOCKS5_PROXY_PORT')
SOCKS5_PROXY_PORT = int(SOCKS5_PROXY_PORT_STR) if SOCKS5_PROXY_PORT_STR and SOCKS5_PROXY_PORT_STR.isdigit() else None
SOCKS5_USERNAME = os.environ.get('SOCKS5_USERNAME')
SOCKS5_PASSWORD = os.environ.get('SOCKS5_PASSWORD')

APP_LISTEN_PORT = int(os.environ.get('APP_PORT', '5000'))
PROXY_VERBOSE_STR = os.environ.get('PROXY_VERBOSE_LOGGING', 'false').lower()
PROXY_VERBOSE = PROXY_VERBOSE_STR == 'true'

EXPECTED_API_KEY = os.environ.get('PROXY_API_KEY')

# Cấu hình cho Turnstile bypass
TURNSTILE_TIMEOUT = int(os.environ.get('TURNSTILE_TIMEOUT', '60000'))  # 60 giây
MAX_TURNSTILE_RETRIES = int(os.environ.get('MAX_TURNSTILE_RETRIES', '3'))
STEALTH_MODE = os.environ.get('STEALTH_MODE', 'true').lower() == 'true'

# User Agent pool
ua = UserAgent()

def get_random_user_agent():
    """Tạo user agent ngẫu nhiên"""
    return ua.random

def get_playwright_proxy_config():
    """Lấy cấu hình proxy cho Playwright"""
    if SOCKS5_PROXY_HOST and SOCKS5_PROXY_PORT:
        proxy_config = {
            'server': f'{SOCKS5_PROXY_HOST}:{SOCKS5_PROXY_PORT}'
        }
        if SOCKS5_USERNAME and SOCKS5_PASSWORD:
            proxy_config['username'] = SOCKS5_USERNAME
            proxy_config['password'] = SOCKS5_PASSWORD
        return proxy_config
    return None

async def bypass_turnstile_with_playwright(target_url: str, client_referer: Optional[str] = None, retries: int = 3):
    """Bypass Turnstile bằng cách tick vào checkbox nếu có"""
    for attempt in range(retries):
        log_prefix = f"TURNSTILE_BYPASS (Attempt {attempt + 1}/{retries}) '{target_url}'"
        if client_referer:
            log_prefix += f" (Referer: '{client_referer}')"
        print(log_prefix)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context_options = {
                    'user_agent': get_random_user_agent(),
                    'viewport': {'width': 1920, 'height': 1080},
                    'locale': 'en-US',
                    'timezone_id': 'America/New_York'
                }
                proxy_config = get_playwright_proxy_config()
                if proxy_config:
                    context_options['proxy'] = proxy_config
                    print(f"  TURNSTILE: Proxy configured: {proxy_config['server']}")
                context = await browser.new_context(**context_options)
                page = await context.new_page()
                if STEALTH_MODE:
                    await stealth_async(page)
                if client_referer:
                    await page.set_extra_http_headers({'Referer': client_referer})
                await page.goto(target_url, wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_timeout(random.randint(1000,2000))

                # Tìm iframe chứa Turnstile checkbox
                iframe_element = await page.query_selector('iframe[src*="challenges.cloudflare.com"]')
                if iframe_element:
                    box = await iframe_element.bounding_box()
                    if box:
                        # Di chuyển chuột tới chính giữa checkbox
                        await page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
                        await page.wait_for_timeout(random.randint(300, 800))
                        await page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                        await page.wait_for_timeout(random.randint(2000, 3500))
                        print("  TURNSTILE: Đã tick vào checkbox.")

                # Đợi xác thực hoàn tất, có thể cần refresh hoặc chờ chuyển trang
                await page.wait_for_timeout(2000)
                try:
                    await page.wait_for_load_state('networkidle', timeout=7000)
                except:
                    pass

                content = await page.content()
                final_url = page.url
                await browser.close()

                # Nếu không còn challenge nữa thì trả về luôn
                if 'challenge' not in content.lower() and 'checking your browser' not in content.lower():
                    print(f"  TURNSTILE: SUCCESS - Đã vượt qua captcha.")
                    return content.encode('utf-8'), 'text/html; charset=utf-8', 200, None, final_url
                else:
                    print(f"  TURNSTILE: FAIL - Vẫn còn challenge (Attempt {attempt + 1})")
                    if attempt < retries - 1:
                        await asyncio.sleep(random.randint(2, 5))
                        continue
        except Exception as e:
            error_msg = f"TURNSTILE_ERROR (Attempt {attempt + 1}): {str(e)}"
            print(error_msg)
            if attempt < retries - 1:
                await asyncio.sleep(random.randint(2, 5))
                continue
            return None, None, 500, error_msg, None
    error_msg = f"TURNSTILE_FAIL: Không thể bypass sau {retries} attempts cho '{target_url}'"
    print(error_msg)
    return None, None, 500, error_msg, None

# Hàm xác thực API Key
def validate_api_key(request: Request, x_api_key: Optional[str], auth_token: Optional[str]):
    if EXPECTED_API_KEY:
        actual_client_api_key = x_api_key or auth_token
        auth_method = "N/A"
        if x_api_key: 
            auth_method = "header 'X-API-Key'"
        elif auth_token: 
            auth_method = "query param 'auth_token'"

        if not actual_client_api_key:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. Thiếu API key. IP: {request.client.host if request.client else 'N/A'}")
            raise HTTPException(status_code=401, detail="Lỗi: Thiếu API key.")
        
        if actual_client_api_key != EXPECTED_API_KEY:
            print(f"AUTH_FAIL: API Key không hợp lệ. IP: {request.client.host if request.client else 'N/A'}")
            raise HTTPException(status_code=403, detail="Lỗi: API key không hợp lệ.")

# Route cho Turnstile bypass
@app.get("/turnstile-bypass", response_class=FastAPIResponse)
async def turnstile_bypass_handler(
    request: Request,
    url: Optional[str] = Query(None, description="URL cần bypass Turnstile"),
    referer: Optional[str] = Query(None, description="Referer header tùy chọn"),
    retries: Optional[int] = Query(None, description="Số lần retry (mặc định: 3, tối đa: 5)"),
    auth_token: Optional[str] = Query(None, description="API key gửi qua query parameter"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key gửi qua header")
):
    validate_api_key(request, x_api_key, auth_token)

    if not url:
        raise HTTPException(status_code=400, detail="Lỗi: Thiếu tham số 'url'.")

    # Validate retries
    actual_retries = retries or MAX_TURNSTILE_RETRIES
    if actual_retries > 5:
        actual_retries = 5
    if actual_retries < 1:
        actual_retries = 1

    content, content_type, status_code, error_message, final_url = await bypass_turnstile_with_playwright(
        url, referer, actual_retries
    )

    if error_message and not content:
        raise HTTPException(status_code=status_code or 500, detail=error_message)
    
    # Thêm headers thông tin
    headers = {}
    if final_url and final_url != url:
        headers['X-Final-URL'] = final_url
    headers['X-Bypass-Method'] = 'turnstile-playwright'
    headers['X-Retries-Used'] = str(actual_retries)
    
    return FastAPIResponse(
        content=content, 
        status_code=status_code or 200, 
        media_type=content_type,
        headers=headers
    )

# Route status
@app.get("/status")
def status_handler():
    return {
        "service": "Advanced Cloudscraper Proxy API with Turnstile Bypass",
        "version": "2.0.0",
        "endpoints": {
            "/turnstile-bypass": "Bypass Cloudflare Turnstile CAPTCHAs",
            "/status": "Service status"
        },
        "features": {
            "turnstile_bypass": True,
            "stealth_mode": STEALTH_MODE,
            "socks5_proxy": bool(SOCKS5_PROXY_HOST and SOCKS5_PROXY_PORT),
            "api_key_auth": bool(EXPECTED_API_KEY)
        },
        "config": {
            "turnstile_timeout": TURNSTILE_TIMEOUT,
            "max_retries": MAX_TURNSTILE_RETRIES,
            "stealth_mode": STEALTH_MODE
        }
    }

if __name__ == '__main__':
    print(f"Advanced Proxy Server với Turnstile Bypass đang khởi động trên http://0.0.0.0:{APP_LISTEN_PORT}")
    print(f"  Endpoints:")
    print(f"    GET /turnstile-bypass  - Bypass Cloudflare Turnstile")
    print(f"    GET /status           - Service status")
    print(f"  Features:")
    print(f"    Stealth Mode: {STEALTH_MODE}")
    print(f"    Max Retries: {MAX_TURNSTILE_RETRIES}")
    print(f"    Timeout: {TURNSTILE_TIMEOUT}ms")
    
    uvicorn.run("proxy_server_advanced:app", host="0.0.0.0", port=APP_LISTEN_PORT, reload=False)

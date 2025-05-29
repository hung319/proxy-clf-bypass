from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
from typing import Optional, Dict, Any
import os
import traceback
import uvicorn
import cloudscraper
import asyncio
import json
import random
import time
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from fake_useragent import UserAgent
import re

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

def get_socks_proxy_settings():
    """Lấy cấu hình SOCKS proxy"""
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

async def detect_turnstile_challenge(page):
    """Phát hiện Turnstile challenge"""
    try:
        # Kiểm tra các selector phổ biến của Turnstile
        turnstile_selectors = [
            'iframe[src*="challenges.cloudflare.com"]',
            '[data-sitekey]',
            '.cf-turnstile',
            '#cf-turnstile',
            'iframe[title*="widget"]'
        ]
        
        for selector in turnstile_selectors:
            element = await page.query_selector(selector)
            if element:
                if PROXY_VERBOSE:
                    print(f"  TURNSTILE: Phát hiện challenge với selector: {selector}")
                return True
        
        # Kiểm tra trong page content
        content = await page.content()
        turnstile_indicators = [
            'challenges.cloudflare.com',
            'cf-turnstile',
            'turnstile',
            'data-sitekey',
            'cloudflare challenge'
        ]
        
        for indicator in turnstile_indicators:
            if indicator.lower() in content.lower():
                if PROXY_VERBOSE:
                    print(f"  TURNSTILE: Phát hiện challenge trong content: {indicator}")
                return True
                
        return False
    except Exception as e:
        if PROXY_VERBOSE:
            print(f"  TURNSTILE: Lỗi khi phát hiện challenge: {str(e)}")
        return False

async def wait_for_turnstile_completion(page, timeout=60000):
    """Chờ Turnstile challenge hoàn thành"""
    try:
        if PROXY_VERBOSE:
            print("  TURNSTILE: Đang chờ challenge hoàn thành...")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout / 1000:
            # Kiểm tra xem page đã redirect hoặc thay đổi chưa
            current_url = page.url
            
            # Chờ một chút
            await page.wait_for_timeout(2000)
            
            # Kiểm tra lại URL
            new_url = page.url
            if new_url != current_url:
                if PROXY_VERBOSE:
                    print(f"  TURNSTILE: URL đã thay đổi từ {current_url} -> {new_url}")
                return True
            
            # Kiểm tra xem challenge còn tồn tại không
            has_challenge = await detect_turnstile_challenge(page)
            if not has_challenge:
                if PROXY_VERBOSE:
                    print("  TURNSTILE: Challenge đã biến mất, có thể đã hoàn thành")
                return True
            
            # Thử click vào các element có thể là Turnstile widget
            try:
                turnstile_widget = await page.query_selector('iframe[src*="challenges.cloudflare.com"], .cf-turnstile, #cf-turnstile')
                if turnstile_widget:
                    await turnstile_widget.click()
                    await page.wait_for_timeout(3000)
            except:
                pass
        
        return False
    except Exception as e:
        if PROXY_VERBOSE:
            print(f"  TURNSTILE: Lỗi khi chờ completion: {str(e)}")
        return False

async def bypass_turnstile_with_playwright(target_url: str, client_referer: Optional[str] = None, retries: int = 3):
    """Bypass Turnstile sử dụng Playwright với stealth mode"""
    
    for attempt in range(retries):
        log_prefix = f"TURNSTILE_BYPASS (Attempt {attempt + 1}/{retries}) '{target_url}'"
        if client_referer:
            log_prefix += f" (Referer: '{client_referer}')"
        
        print(log_prefix)
        
        try:
            async with async_playwright() as p:
                # Tạo browser với args để tránh phát hiện
                browser_args = [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding',
                    '--disable-features=TranslateUI',
                    '--disable-ipc-flooding-protection',
                    '--enable-features=NetworkService,NetworkServiceLogging',
                    '--force-device-scale-factor=1',
                    '--hide-scrollbars',
                    '--mute-audio',
                    '--disable-extensions',
                    '--disable-plugins',
                    '--disable-images'  # Tăng tốc độ load
                ]
                
                browser = await p.chromium.launch(
                    headless=True,
                    args=browser_args
                )
                
                # Tạo context với cấu hình anti-detection
                context_options = {
                    'user_agent': get_random_user_agent(),
                    'viewport': {'width': 1920, 'height': 1080},
                    'locale': 'en-US',
                    'timezone_id': 'America/New_York',
                    'permissions': [],
                    'extra_http_headers': {
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Cache-Control': 'max-age=0'
                    }
                }
                
                # Thêm proxy nếu có
                proxy_config = get_playwright_proxy_config()
                if proxy_config:
                    context_options['proxy'] = proxy_config
                    print(f"  TURNSTILE: Proxy configured: {proxy_config['server']}")
                
                context = await browser.new_context(**context_options)
                
                # Apply stealth mode
                page = await context.new_page()
                if STEALTH_MODE:
                    await stealth_async(page)
                
                # Set additional headers
                if client_referer:
                    await page.set_extra_http_headers({'Referer': client_referer})
                
                # Override webdriver detection
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined,
                    });
                    
                    // Override the plugins property to use a custom getter
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5],
                    });
                    
                    // Override languages
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en'],
                    });
                    
                    // Override permissions
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                """)
                
                # Random delay để tránh pattern detection
                await page.wait_for_timeout(random.randint(2000, 5000))
                
                if PROXY_VERBOSE:
                    print(f"  TURNSTILE: Đang truy cập {target_url}...")
                
                # Truy cập trang
                response = await page.goto(target_url, wait_until='domcontentloaded', timeout=30000)
                
                # Chờ trang load hoàn toàn
                await page.wait_for_timeout(3000)
                
                # Kiểm tra Turnstile challenge
                has_turnstile = await detect_turnstile_challenge(page)
                
                if has_turnstile:
                    if PROXY_VERBOSE:
                        print("  TURNSTILE: Phát hiện challenge, đang xử lý...")
                    
                    # Chờ challenge completion
                    success = await wait_for_turnstile_completion(page, TURNSTILE_TIMEOUT)
                    
                    if not success:
                        print(f"  TURNSTILE: Timeout sau {TURNSTILE_TIMEOUT}ms")
                        await browser.close()
                        continue
                    
                    # Chờ thêm một chút sau khi challenge hoàn thành
                    await page.wait_for_timeout(3000)
                
                # Chờ network idle để đảm bảo trang load hoàn toàn
                try:
                    await page.wait_for_load_state('networkidle', timeout=10000)
                except:
                    pass
                
                # Lấy nội dung cuối cùng
                content = await page.content()
                final_url = page.url
                
                await browser.close()
                
                # Kiểm tra xem có bypass thành công không
                if 'challenge' not in content.lower() and 'checking your browser' not in content.lower():
                    if PROXY_VERBOSE:
                        print(f"  TURNSTILE: SUCCESS - Bypass thành công cho '{target_url}' -> '{final_url}'")
                    return content.encode('utf-8'), 'text/html; charset=utf-8', 200, None, final_url
                else:
                    print(f"  TURNSTILE: FAIL - Vẫn có challenge trong content (Attempt {attempt + 1})")
                    if attempt < retries - 1:
                        await asyncio.sleep(random.randint(5, 10))  # Random delay trước retry
                        continue
                
        except Exception as e:
            error_msg = f"TURNSTILE_ERROR (Attempt {attempt + 1}): {str(e)}"
            print(error_msg)
            if attempt < retries - 1:
                await asyncio.sleep(random.randint(3, 7))
                continue
            return None, None, 500, error_msg, None
    
    # Tất cả attempts đều fail
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

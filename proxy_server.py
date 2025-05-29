from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
from typing import Optional
import os
import traceback
import uvicorn
import cloudscraper
import asyncio
from playwright.async_api import async_playwright
import json

# Khởi tạo ứng dụng FastAPI
app = FastAPI(title="Cloudscraper Proxy API with JS Rendering", version="1.1.0")

# --- Đọc Cấu Hình Từ Biến Môi Trường ---
SOCKS5_PROXY_HOST = os.environ.get('SOCKS5_PROXY_HOST')
SOCKS5_PROXY_PORT_STR = os.environ.get('SOCKS5_PROXY_PORT')
SOCKS5_PROXY_PORT = int(SOCKS5_PROXY_PORT_STR) if SOCKS5_PROXY_PORT_STR and SOCKS5_PROXY_PORT_STR.isdigit() else None
SOCKS5_USERNAME = os.environ.get('SOCKS5_USERNAME')
SOCKS5_PASSWORD = os.environ.get('SOCKS5_PASSWORD')

APP_LISTEN_PORT = int(os.environ.get('APP_PORT', '5000'))
PROXY_VERBOSE_STR = os.environ.get('PROXY_VERBOSE_LOGGING', 'false').lower()
PROXY_VERBOSE = PROXY_VERBOSE_STR == 'true'

EXPECTED_API_KEY = os.environ.get('PROXY_API_KEY')

# Cấu hình cho JS rendering
JS_RENDER_TIMEOUT = int(os.environ.get('JS_RENDER_TIMEOUT', '30000'))  # 30 giây
JS_RENDER_WAIT_FOR = os.environ.get('JS_RENDER_WAIT_FOR', 'networkidle')  # hoặc 'domcontentloaded', 'load'

# --- Kết Thúc Đọc Cấu Hình ---

# Hàm get_socks_proxy_settings (Giữ nguyên)
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

# Hàm fetch_final_content_from_url (Giữ nguyên)
def fetch_final_content_from_url(target_url: str, client_referer: Optional[str] = None):
    active_proxies = get_socks_proxy_settings()
    log_prefix = f"Proxying '{target_url}'"
    if client_referer:
        log_prefix += f" (Referer: '{client_referer}')"
    
    print(log_prefix) 

    # Tạo scraper
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
    )

    if active_proxies:
        scraper.proxies = active_proxies
        print(f"  SOCKS5 Proxy configured for this request: {active_proxies.get('http')}")
    elif PROXY_VERBOSE:
        print("  No SOCKS5 Proxy configured for this request.")

    try:
        initial_request_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
            'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8', 'Connection': 'keep-alive',
        }
        if client_referer:
            initial_request_headers['Referer'] = client_referer

        if PROXY_VERBOSE:
            print(f"  VERBOSE: Bước 1 - Truy cập URL ban đầu: {target_url}")
        initial_response = scraper.get(target_url, headers=initial_request_headers, allow_redirects=True)
        if PROXY_VERBOSE:
            print(f"  VERBOSE: Bước 1 - Status: {initial_response.status_code}, URL cuối: {initial_response.url}")

        initial_response_headers = dict(initial_response.headers)
        current_url_after_step1 = initial_response.url
        response_for_content = initial_response

        final_url_from_header = None
        if 'Zr-Final-Url' in initial_response_headers:
            final_url_from_header = initial_response_headers['Zr-Final-Url']
        elif initial_response.status_code in [200, 201, 202] and 'Location' in initial_response_headers:
            final_url_from_header = initial_response_headers['Location']
        elif initial_response.status_code >= 300 and initial_response.status_code < 400 and 'Location' in initial_response_headers:
             final_url_from_header = initial_response_headers['Location']

        if final_url_from_header and final_url_from_header != current_url_after_step1:
            if PROXY_VERBOSE:
                print(f"  VERBOSE: Bước 2 - Tìm thấy URL đích trong header: {final_url_from_header}. Truy cập nó.")
            final_request_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
                'Accept': '*/*', 'Referer': current_url_after_step1
            }
            final_response = scraper.get(final_url_from_header, headers=final_request_headers, allow_redirects=True)
            if PROXY_VERBOSE:
                print(f"  VERBOSE: Bước 2 - Status: {final_response.status_code}, URL cuối: {final_response.url}")
            response_for_content = final_response
        
        final_url_accessed = response_for_content.url
        final_status_code = response_for_content.status_code

        if final_status_code == 200:
            content = response_for_content.content
            content_type = response_for_content.headers.get('Content-Type', 'application/octet-stream')
            if PROXY_VERBOSE:
                print(f"  SUCCESS: '{target_url}' -> '{final_url_accessed}' (Status: {final_status_code}, Type: {content_type})")
            return content, content_type, final_status_code, None
        else:
            error_msg = f"ERROR: Target URL '{final_url_accessed}' responded with {final_status_code} - {response_for_content.reason} (Original URL: '{target_url}')"
            print(error_msg)
            return response_for_content.content, \
                   response_for_content.headers.get('Content-Type', 'text/plain'), \
                   final_status_code, \
                   error_msg

    except Exception as e:
        error_msg = f"CRITICAL_ERROR: Exception while processing '{target_url}': {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        return None, None, 500, error_msg

# Hàm mới: render JavaScript với Playwright
async def fetch_js_rendered_content(target_url: str, client_referer: Optional[str] = None, wait_for: str = 'networkidle', timeout: int = 30000, custom_js: Optional[str] = None):
    """
    Render JavaScript và trả về nội dung đã được render
    
    Args:
        target_url: URL cần truy cập
        client_referer: Referer header
        wait_for: Điều kiện chờ ('networkidle', 'domcontentloaded', 'load')
        timeout: Timeout trong milliseconds
        custom_js: JavaScript tùy chỉnh để thực thi
    """
    log_prefix = f"JS Rendering '{target_url}'"
    if client_referer:
        log_prefix += f" (Referer: '{client_referer}')"
    
    print(log_prefix)
    
    try:
        async with async_playwright() as p:
            # Khởi tạo trình duyệt
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            
            # Cấu hình proxy nếu có
            active_proxies = get_socks_proxy_settings()
            if active_proxies and SOCKS5_PROXY_HOST and SOCKS5_PROXY_PORT:
                # Playwright hỗ trợ proxy khác với requests
                proxy_config = {
                    'server': f'{SOCKS5_PROXY_HOST}:{SOCKS5_PROXY_PORT}'
                }
                if SOCKS5_USERNAME and SOCKS5_PASSWORD:
                    proxy_config['username'] = SOCKS5_USERNAME
                    proxy_config['password'] = SOCKS5_PASSWORD
                
                # Tạo context mới với proxy
                await context.close()
                context = await browser.new_context(
                    proxy=proxy_config,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                print(f"  SOCKS5 Proxy configured for JS rendering: {SOCKS5_PROXY_HOST}:{SOCKS5_PROXY_PORT}")
            
            page = await context.new_page()
            
            # Set referer nếu có
            if client_referer:
                await page.set_extra_http_headers({'Referer': client_referer})
            
            if PROXY_VERBOSE:
                print(f"  VERBOSE: Đang truy cập {target_url} với JS rendering...")
            
            # Truy cập trang và chờ render
            if wait_for == 'networkidle':
                await page.goto(target_url, wait_until='networkidle', timeout=timeout)
            elif wait_for == 'domcontentloaded':
                await page.goto(target_url, wait_until='domcontentloaded', timeout=timeout)
            elif wait_for == 'load':
                await page.goto(target_url, wait_until='load', timeout=timeout)
            else:
                await page.goto(target_url, timeout=timeout)
            
            # Thực thi JavaScript tùy chỉnh nếu có
            if custom_js:
                if PROXY_VERBOSE:
                    print(f"  VERBOSE: Thực thi JavaScript tùy chỉnh...")
                await page.evaluate(custom_js)
                # Chờ thêm một chút để JS hoàn thành
                await page.wait_for_timeout(2000)
            
            # Lấy nội dung đã render
            content = await page.content()
            final_url = page.url
            
            await browser.close()
            
            if PROXY_VERBOSE:
                print(f"  SUCCESS: JS Rendering completed for '{target_url}' -> '{final_url}'")
            
            return content.encode('utf-8'), 'text/html; charset=utf-8', 200, None, final_url
            
    except Exception as e:
        error_msg = f"JS_RENDER_ERROR: Exception while rendering '{target_url}': {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
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
            raise HTTPException(status_code=401, detail="Lỗi: Thiếu API key. Vui lòng cung cấp 'X-API-Key' header hoặc 'auth_token' query parameter.")
        
        if actual_client_api_key != EXPECTED_API_KEY:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. API Key không hợp lệ (phương thức: {auth_method}). IP: {request.client.host if request.client else 'N/A'}")
            raise HTTPException(status_code=403, detail="Lỗi: API key không hợp lệ.")
        
        if PROXY_VERBOSE:
            print(f"AUTH_SUCCESS: API Key hợp lệ (phương thức: {auth_method}). IP: {request.client.host if request.client else 'N/A'}")

# Route gốc (cloudscraper)
@app.get("/", response_class=FastAPIResponse)
def proxy_handler(
    request: Request,
    url: Optional[str] = Query(None, description="URL cần proxy truy cập"),
    referer: Optional[str] = Query(None, description="Referer header tùy chọn cho request đến target URL"),
    auth_token: Optional[str] = Query(None, description="API key gửi qua query parameter"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key gửi qua header")
):
    validate_api_key(request, x_api_key, auth_token)

    if not url:
        raise HTTPException(status_code=400, detail="Lỗi: Thiếu tham số 'url'. Cách dùng: /?url=<URL_CẦN_TRUY_CẬP>")

    content, content_type, status_code, error_message = fetch_final_content_from_url(url, referer)

    if error_message and not content:
         raise HTTPException(status_code=status_code or 500, detail=error_message or "Lỗi không xác định từ proxy server")
    
    return FastAPIResponse(content=content, status_code=status_code or 200, media_type=content_type)

# Route mới: JS Rendering
@app.get("/js-render", response_class=FastAPIResponse)
async def js_render_handler(
    request: Request,
    url: Optional[str] = Query(None, description="URL cần render JavaScript"),
    referer: Optional[str] = Query(None, description="Referer header tùy chọn"),
    wait_for: Optional[str] = Query('networkidle', description="Điều kiện chờ: networkidle, domcontentloaded, load"),
    timeout: Optional[int] = Query(None, description="Timeout trong milliseconds (mặc định: 30000)"),
    js_code: Optional[str] = Query(None, description="JavaScript tùy chỉnh để thực thi sau khi trang load"),
    auth_token: Optional[str] = Query(None, description="API key gửi qua query parameter"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key gửi qua header")
):
    validate_api_key(request, x_api_key, auth_token)

    if not url:
        raise HTTPException(status_code=400, detail="Lỗi: Thiếu tham số 'url'. Cách dùng: /js-render?url=<URL_CẦN_RENDER>")

    # Validate wait_for parameter
    valid_wait_options = ['networkidle', 'domcontentloaded', 'load']
    if wait_for not in valid_wait_options:
        wait_for = 'networkidle'
    
    # Set timeout
    actual_timeout = timeout or JS_RENDER_TIMEOUT
    if actual_timeout > 120000:  # Giới hạn tối đa 2 phút
        actual_timeout = 120000

    content, content_type, status_code, error_message, final_url = await fetch_js_rendered_content(
        url, referer, wait_for, actual_timeout, js_code
    )

    if error_message and not content:
        raise HTTPException(status_code=status_code or 500, detail=error_message or "Lỗi không xác định từ JS renderer")
    
    # Thêm header để client biết URL cuối cùng
    headers = {}
    if final_url and final_url != url:
        headers['X-Final-URL'] = final_url
    
    return FastAPIResponse(
        content=content, 
        status_code=status_code or 200, 
        media_type=content_type,
        headers=headers
    )

# Route để lấy thông tin status
@app.get("/status")
def status_handler():
    return {
        "service": "Cloudscraper Proxy API with JS Rendering",
        "version": "1.1.0",
        "endpoints": {
            "/": "Standard proxy using cloudscraper",
            "/js-render": "JavaScript rendering proxy using Playwright",
            "/status": "Service status"
        },
        "features": {
            "cloudscraper": True,
            "js_rendering": True,
            "socks5_proxy": bool(SOCKS5_PROXY_HOST and SOCKS5_PROXY_PORT),
            "api_key_auth": bool(EXPECTED_API_KEY)
        }
    }

if __name__ == '__main__':
    print(f"FastAPI Proxy server với JS Rendering đang khởi động trên http://0.0.0.0:{APP_LISTEN_PORT}")
    if EXPECTED_API_KEY:
        print(f"  API Key Authentication IS ENABLED.")
    else:
        print(f"  WARNING: API Key Authentication IS DISABLED.")
    
    print(f"  Endpoints available:")
    print(f"    GET /           - Standard proxy (cloudscraper)")
    print(f"    GET /js-render  - JavaScript rendering proxy (Playwright)")
    print(f"    GET /status     - Service status")
    
    if PROXY_VERBOSE:
        print("  VERBOSE logging is ENABLED.")
    else:
        print("  VERBOSE logging is DISABLED.")
    
    uvicorn.run("proxy_server:app", host="0.0.0.0", port=APP_LISTEN_PORT, reload=(os.environ.get("DEV_MODE", "false").lower() == "true"))

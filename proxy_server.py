from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
from typing import Optional
import os
import traceback
import uvicorn
import cloudscraper

# Import Playwright
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

app = FastAPI(title="Cloudscraper Proxy API with JS Rendering", version="1.1.0")

# --- Đọc Cấu Hình Từ Biến Môi Trường (Giữ nguyên) ---
SOCKS5_PROXY_HOST = os.environ.get('SOCKS5_PROXY_HOST')
SOCKS5_PROXY_PORT_STR = os.environ.get('SOCKS5_PROXY_PORT')
SOCKS5_PROXY_PORT = int(SOCKS5_PROXY_PORT_STR) if SOCKS5_PROXY_PORT_STR and SOCKS5_PROXY_PORT_STR.isdigit() else None
SOCKS5_USERNAME = os.environ.get('SOCKS5_USERNAME')
SOCKS5_PASSWORD = os.environ.get('SOCKS5_PASSWORD')

APP_LISTEN_PORT = int(os.environ.get('APP_PORT', '5000'))
PROXY_VERBOSE_STR = os.environ.get('PROXY_VERBOSE_LOGGING', 'false').lower()
PROXY_VERBOSE = PROXY_VERBOSE_STR == 'true'
EXPECTED_API_KEY = os.environ.get('PROXY_API_KEY')
# --- Kết Thúc Đọc Cấu Hình ---

# (Hàm get_socks_proxy_settings giữ nguyên)
def get_socks_proxy_settings():
    if SOCKS5_PROXY_HOST and SOCKS5_PROXY_PORT:
        proxy_url_scheme = 'socks5h' # socks5h để DNS resolution cũng qua proxy
        auth_part = ''
        if SOCKS5_USERNAME and SOCKS5_PASSWORD:
            auth_part = f'{SOCKS5_USERNAME}:{SOCKS5_PASSWORD}@'
        elif SOCKS5_USERNAME:
            auth_part = f'{SOCKS5_USERNAME}@'
        proxy_full_url = f'{proxy_url_scheme}://{auth_part}{SOCKS5_PROXY_HOST}:{SOCKS5_PROXY_PORT}'
        return {'http': proxy_full_url, 'https': proxy_full_url}
    return None

def fetch_final_content_from_url(target_url: str, client_referer: Optional[str] = None, render_js: bool = False):
    active_proxies_for_requests = get_socks_proxy_settings() # Dùng cho Cloudscraper/requests
    log_prefix = f"Proxying '{target_url}'"
    if client_referer: log_prefix += f" (Referer: '{client_referer}')"
    if render_js: log_prefix += " [JS Rendering ON]"
    
    # Thông tin SOCKS sẽ được log bên trong mỗi nhánh (Cloudscraper / Playwright)
    print(log_prefix)

    if render_js:
        content = None
        content_type = 'text/html'  # Mặc định cho trang đã render
        status_code = 500           # Mặc định lỗi
        final_url_accessed = target_url
        error_message_detail = "JS rendering failed"

        playwright_proxy_config = None
        if SOCKS5_PROXY_HOST and SOCKS5_PROXY_PORT:
            playwright_proxy_config = {
                "server": f"socks5://{SOCKS5_PROXY_HOST}:{SOCKS5_PROXY_PORT}"
            }
            if SOCKS5_USERNAME:
                playwright_proxy_config["username"] = SOCKS5_USERNAME
            if SOCKS5_PASSWORD:
                playwright_proxy_config["password"] = SOCKS5_PASSWORD
            if PROXY_VERBOSE:
                print(f"  VERBOSE: Playwright attempting to use SOCKS5 proxy: {playwright_proxy_config['server']}")
        elif PROXY_VERBOSE:
            print("  VERBOSE: Playwright: No SOCKS5 Proxy configured.")


        try:
            with sync_playwright() as p:
                # Khởi chạy trình duyệt. Bạn có thể chọn p.chromium, p.firefox, hoặc p.webkit
                browser = p.chromium.launch(
                    headless=True,
                    # proxy=playwright_proxy_config # Sẽ áp dụng ở context
                    args=['--no-sandbox', '--disable-setuid-sandbox'] # Thường cần thiết khi chạy trong Docker với user không phải root
                )
                
                context_options = {}
                if playwright_proxy_config:
                    context_options["proxy"] = playwright_proxy_config
                
                # Thêm user agent giống Cloudscraper (tùy chọn)
                # context_options["user_agent"] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36'


                browser_context = browser.new_context(**context_options)
                page = browser_context.new_page()

                if client_referer:
                    page.set_extra_http_headers({"Referer": client_referer})

                if PROXY_VERBOSE:
                    print(f"  VERBOSE: Playwright navigating to {target_url}")
                
                # Timeout mặc định của Playwright là 30 giây cho page.goto()
                # wait_until: 'load', 'domcontentloaded', 'networkidle', 'commit'
                pw_response = page.goto(target_url, timeout=60000, wait_until="networkidle") # Tăng timeout và chờ network idle

                content_str = page.content() # Lấy HTML sau khi JS chạy
                content = content_str.encode('utf-8')
                
                status_code = pw_response.status if pw_response else 200 
                # Content-Type có thể phức tạp hơn với JS rendering, nhưng thường là text/html
                # pw_response.header_value('content-type') có thể trả về charset, v.v.
                retrieved_content_type = pw_response.headers.get('content-type', 'text/html; charset=utf-8') if pw_response else 'text/html; charset=utf-8'
                content_type = retrieved_content_type.split(';')[0].strip() # Lấy phần chính của content type

                final_url_accessed = page.url
                error_message_detail = None # Thành công

                browser_context.close() # Quan trọng: đóng context
                browser.close() # Quan trọng: đóng browser

            if PROXY_VERBOSE:
                print(f"  SUCCESS (JS Rendered): '{target_url}' -> '{final_url_accessed}' (Status: {status_code}, Type: {content_type})")
            return content, content_type, status_code, error_message_detail

        except PlaywrightTimeoutError:
            error_message_detail = f"JS rendering timed out for {target_url} after 60s"
            print(f"  ERROR: {error_message_detail}")
            return None, "text/plain", 504, error_message_detail # 504 Gateway Timeout
        except PlaywrightError as e_pw_specific: # Bắt các lỗi cụ thể của Playwright
            error_message_detail = f"Playwright specific error for {target_url}: {type(e_pw_specific).__name__} - {str(e_pw_specific)}"
            print(f"  ERROR: {error_message_detail}")
            if PROXY_VERBOSE: print(traceback.format_exc())
            return None, "text/plain", 502, error_message_detail # 502 Bad Gateway có thể phù hợp
        except Exception as e_pw: # Bắt các lỗi chung khác
            error_message_detail = f"General JS rendering failed for {target_url}: {str(e_pw)}"
            print(f"  ERROR: {error_message_detail}")
            print(traceback.format_exc())
            return None, "text/plain", 500, error_message_detail
    else:
        # --- Logic Cloudscraper hiện tại ---
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
        )
        if active_proxies_for_requests:
            scraper.proxies = active_proxies_for_requests
            if PROXY_VERBOSE:
                print(f"  VERBOSE: Cloudscraper using SOCKS5 Proxy: {active_proxies_for_requests.get('http')}")
        elif PROXY_VERBOSE:
            print("  VERBOSE: Cloudscraper: No SOCKS5 Proxy configured.")
        
        # (Copy toàn bộ logic Cloudscraper từ phiên bản trước vào đây)
        try:
            initial_request_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
                'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8', 'Connection': 'keep-alive',
            }
            if client_referer:
                initial_request_headers['Referer'] = client_referer

            if PROXY_VERBOSE:
                print(f"  VERBOSE (Cloudscraper): Bước 1 - Truy cập URL ban đầu: {target_url}")
            cs_initial_response = scraper.get(target_url, headers=initial_request_headers, allow_redirects=True)
            if PROXY_VERBOSE:
                print(f"  VERBOSE (Cloudscraper): Bước 1 - Status: {cs_initial_response.status_code}, URL cuối: {cs_initial_response.url}")

            cs_initial_response_headers = dict(cs_initial_response.headers)
            cs_current_url_after_step1 = cs_initial_response.url
            cs_response_for_content = cs_initial_response

            cs_final_url_from_header = None
            if 'Zr-Final-Url' in cs_initial_response_headers:
                cs_final_url_from_header = cs_initial_response_headers['Zr-Final-Url']
            elif cs_initial_response.status_code in [200, 201, 202] and 'Location' in cs_initial_response_headers:
                cs_final_url_from_header = cs_initial_response_headers['Location']
            elif cs_initial_response.status_code >= 300 and cs_initial_response.status_code < 400 and 'Location' in cs_initial_response_headers:
                 cs_final_url_from_header = cs_initial_response_headers['Location']

            if cs_final_url_from_header and cs_final_url_from_header != cs_current_url_after_step1:
                if PROXY_VERBOSE:
                    print(f"  VERBOSE (Cloudscraper): Bước 2 - Tìm thấy URL đích trong header: {cs_final_url_from_header}. Truy cập nó.")
                final_request_headers_cs = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
                    'Accept': '*/*', 'Referer': cs_current_url_after_step1
                }
                cs_final_response = scraper.get(cs_final_url_from_header, headers=final_request_headers_cs, allow_redirects=True)
                if PROXY_VERBOSE:
                    print(f"  VERBOSE (Cloudscraper): Bước 2 - Status: {cs_final_response.status_code}, URL cuối: {cs_final_response.url}")
                cs_response_for_content = cs_final_response
            
            final_url_accessed_cs = cs_response_for_content.url
            final_status_code_cs = cs_response_for_content.status_code

            if final_status_code_cs == 200:
                content_cs = cs_response_for_content.content
                content_type_cs = cs_response_for_content.headers.get('Content-Type', 'application/octet-stream')
                if PROXY_VERBOSE:
                    print(f"  SUCCESS (Cloudscraper): '{target_url}' -> '{final_url_accessed_cs}' (Status: {final_status_code_cs}, Type: {content_type_cs})")
                return content_cs, content_type_cs, final_status_code_cs, None
            else:
                error_msg_cs = f"ERROR (Cloudscraper): Target URL '{final_url_accessed_cs}' responded with {final_status_code_cs} - {cs_response_for_content.reason} (Original URL: '{target_url}')"
                print(error_msg_cs)
                return cs_response_for_content.content, \
                       cs_response_for_content.headers.get('Content-Type', 'text/plain'), \
                       final_status_code_cs, \
                       error_msg_cs
        except Exception as e_cs:
            error_msg_cs = f"CRITICAL_ERROR (Cloudscraper): Exception while processing '{target_url}': {str(e_cs)}"
            print(error_msg_cs)
            print(traceback.format_exc())
            return None, None, 500, error_msg_cs


# Cập nhật proxy_handler để nhận tham số 'js'
@app.get("/", response_class=FastAPIResponse)
def proxy_handler(
    request: Request,
    url: Optional[str] = Query(None, description="URL cần proxy truy cập"),
    referer: Optional[str] = Query(None, description="Referer header tùy chọn cho request đến target URL"),
    auth_token: Optional[str] = Query(None, description="API key gửi qua query parameter"),
    js: Optional[str] = Query(None, description="Bật JS rendering nếu giá trị là 'on' hoặc 'true'"), # Thêm tham số js
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key gửi qua header")
):
    # (Logic xác thực API Key giữ nguyên)
    if EXPECTED_API_KEY:
        actual_client_api_key = x_api_key or auth_token 
        auth_method = "N/A"
        if x_api_key: auth_method = "header 'X-API-Key'"
        elif auth_token: auth_method = "query param 'auth_token'"

        if not actual_client_api_key:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. Thiếu API key. IP: {request.client.host if request.client else 'N/A'}")
            raise HTTPException(status_code=401, detail="Lỗi: Thiếu API key. Vui lòng cung cấp 'X-API-Key' header hoặc 'auth_token' query parameter.")
        
        if actual_client_api_key != EXPECTED_API_KEY:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. API Key không hợp lệ (phương thức: {auth_method}). IP: {request.client.host if request.client else 'N/A'}, Key: '{actual_client_api_key[:10]}...'")
            raise HTTPException(status_code=403, detail="Lỗi: API key không hợp lệ.")
        
        if PROXY_VERBOSE:
            print(f"AUTH_SUCCESS: API Key hợp lệ (phương thức: {auth_method}). IP: {request.client.host if request.client else 'N/A'}")

    if not url:
        raise HTTPException(status_code=400, detail="Lỗi: Thiếu tham số 'url'. Cách dùng: /?url=<URL_CẦN_TRUY_CẬP>")

    # Kiểm tra tham số 'js' để quyết định có render JS không
    should_render_js = js and js.lower() in ["on", "true", "1"]

    content, content_type, status_code, error_message = fetch_final_content_from_url(url, referer, render_js=should_render_js)

    if error_message and not content:
         raise HTTPException(status_code=status_code or 500, detail=error_message or "Lỗi không xác định từ proxy server")
    
    return FastAPIResponse(content=content, status_code=status_code or 200, media_type=content_type)


if __name__ == '__main__':
    # (Khối if __name__ == '__main__' giữ nguyên)
    print(f"FastAPI Proxy server (chạy trực tiếp với Uvicorn) đang khởi động trên http://0.0.0.0:{APP_LISTEN_PORT}")
    if EXPECTED_API_KEY:
        print(f"  API Key Authentication IS ENABLED. Client cần cung cấp 'X-API-Key' header hoặc 'auth_token' query parameter.")
    else:
        print(f"  WARNING: API Key Authentication IS DISABLED. Proxy đang mở. (PROXY_API_KEY chưa được thiết lập)")
    
    if PROXY_VERBOSE:
        print("  VERBOSE logging is ENABLED.")
    else:
        print("  VERBOSE logging is DISABLED. Set PROXY_VERBOSE_LOGGING=true to enable.")
    
    uvicorn.run("proxy_server:app", host="0.0.0.0", port=APP_LISTEN_PORT, reload= (os.environ.get("DEV_MODE", "false").lower() == "true") )

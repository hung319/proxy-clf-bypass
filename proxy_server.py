from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
from typing import Optional
import os
import traceback
import uvicorn # Thêm để chạy uvicorn từ if __name__ == '__main__'
import cloudscraper # Giữ nguyên cloudscraper

# Khởi tạo ứng dụng FastAPI
app = FastAPI(title="Cloudscraper Proxy API", version="1.0.0")

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

# Hàm fetch_final_content_from_url (Logic cốt lõi giữ nguyên, chỉ thay đổi cách gọi debug của cloudscraper nếu muốn)
def fetch_final_content_from_url(target_url: str, client_referer: Optional[str] = None):
    active_proxies = get_socks_proxy_settings()
    log_prefix = f"Proxying '{target_url}'"
    if client_referer:
        log_prefix += f" (Referer: '{client_referer}')"
    
    print(log_prefix) 

    # Tạo scraper
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
        # debug=PROXY_VERBOSE # Cloudscraper debug có thể rất nhiều log
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


# Định nghĩa route với FastAPI
# Sử dụng `def` thay vì `async def` vì `Workspace_final_content_from_url` là synchronous.
# FastAPI sẽ tự động chạy các hàm `def` trong một thread pool.
@app.get("/", response_class=FastAPIResponse) # Sử dụng FastAPIResponse để trả về nội dung tùy chỉnh
def proxy_handler(
    request: Request, # Đối tượng Request của FastAPI để lấy thông tin client IP
    url: Optional[str] = Query(None, description="URL cần proxy truy cập"),
    referer: Optional[str] = Query(None, description="Referer header tùy chọn cho request đến target URL"),
    auth_token: Optional[str] = Query(None, description="API key gửi qua query parameter"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key gửi qua header")
):
    # --- Xác thực API Key (logic tương tự Flask) ---
    if EXPECTED_API_KEY:
        actual_client_api_key = x_api_key or auth_token # Ưu tiên header
        auth_method = "N/A"
        if x_api_key: auth_method = "header 'X-API-Key'"
        elif auth_token: auth_method = "query param 'auth_token'"

        if not actual_client_api_key:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. Thiếu API key. IP: {request.client.host if request.client else 'N/A'}")
            # Sử dụng HTTPException của FastAPI để trả lỗi chuẩn
            raise HTTPException(status_code=401, detail="Lỗi: Thiếu API key. Vui lòng cung cấp 'X-API-Key' header hoặc 'auth_token' query parameter.")
        
        if actual_client_api_key != EXPECTED_API_KEY:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. API Key không hợp lệ (phương thức: {auth_method}). IP: {request.client.host if request.client else 'N/A'}, Key: '{actual_client_api_key[:10]}...'")
            raise HTTPException(status_code=403, detail="Lỗi: API key không hợp lệ.")
        
        if PROXY_VERBOSE:
            print(f"AUTH_SUCCESS: API Key hợp lệ (phương thức: {auth_method}). IP: {request.client.host if request.client else 'N/A'}")
    # --- Kết thúc xác thực API Key ---

    if not url:
        raise HTTPException(status_code=400, detail="Lỗi: Thiếu tham số 'url'. Cách dùng: /?url=<URL_CẦN_TRUY_CẬP>")

    content, content_type, status_code, error_message = fetch_final_content_from_url(url, referer)

    if error_message and not content: # Lỗi nghiêm trọng từ fetch_final_content_from_url
         # Trả về lỗi 500 nếu fetch_final_content_from_url trả về status 500
         # Hoặc một mã lỗi khác tùy theo error_message nếu muốn chi tiết hơn
         raise HTTPException(status_code=status_code or 500, detail=error_message or "Lỗi không xác định từ proxy server")
    
    # Trả về nội dung thành công hoặc nội dung lỗi từ server đích
    # media_type cần được set chính xác
    return FastAPIResponse(content=content, status_code=status_code or 200, media_type=content_type)


if __name__ == '__main__':
    print(f"FastAPI Proxy server (chạy trực tiếp với Uvicorn) đang khởi động trên http://0.0.0.0:{APP_LISTEN_PORT}")
    if EXPECTED_API_KEY:
        print(f"  API Key Authentication IS ENABLED. Client cần cung cấp 'X-API-Key' header hoặc 'auth_token' query parameter.")
    else:
        print(f"  WARNING: API Key Authentication IS DISABLED. Proxy đang mở. (PROXY_API_KEY chưa được thiết lập)")
    
    if PROXY_VERBOSE:
        print("  VERBOSE logging is ENABLED.")
    else:
        print("  VERBOSE logging is DISABLED. Set PROXY_VERBOSE_LOGGING=true to enable.")
    
    # Chạy uvicorn. debug=True hoặc reload=True chỉ nên dùng cho phát triển.
    # Trong Docker, uvicorn sẽ được chạy qua CMD.
    uvicorn.run("proxy_server:app", host="0.0.0.0", port=APP_LISTEN_PORT, reload= (os.environ.get("DEV_MODE", "false").lower() == "true") )

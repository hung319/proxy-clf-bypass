from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional, AsyncGenerator
import os
import traceback
import uvicorn
import cloudscraper
import asyncio # Thêm asyncio để sử dụng asyncio.to_thread
import requests # Để type hint và xử lý exceptions của requests

# Khởi tạo ứng dụng FastAPI
app = FastAPI(title="Cloudscraper Proxy API (Optimized)", version="1.1.0")

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

# Lớp Exception tùy chỉnh để xử lý lỗi rõ ràng hơn từ fetch logic
class ProxyFetchError(Exception):
    def __init__(self, message: str, status_code: int = 500, content: Optional[bytes] = None, content_type: str = 'text/plain'):
        super().__init__(message)
        self.status_code = status_code
        self.content = content if content is not None else str(message).encode('utf-8')
        self.content_type = content_type

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

# Hàm fetch_final_content_from_url được sửa đổi để trả về đối tượng response
# và sử dụng stream=True, đồng thời raise ProxyFetchError khi có lỗi.
def fetch_target_response(target_url: str, client_referer: Optional[str] = None) -> requests.Response:
    active_proxies = get_socks_proxy_settings()
    log_prefix = f"Proxying '{target_url}'"
    if client_referer:
        log_prefix += f" (Referer: '{client_referer}')"
    
    if PROXY_VERBOSE:
        print(log_prefix)

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
        # debug=PROXY_VERBOSE # Bật khi cần debug sâu cloudscraper
    )

    if active_proxies:
        scraper.proxies = active_proxies
        if PROXY_VERBOSE:
            print(f"  SOCKS5 Proxy configured for this request: {active_proxies.get('http')}")
    elif PROXY_VERBOSE:
        print("  No SOCKS5 Proxy configured for this request.")

    response_for_content: Optional[requests.Response] = None
    initial_response: Optional[requests.Response] = None

    try:
        initial_request_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
            'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8', 'Connection': 'keep-alive',
        }
        if client_referer:
            initial_request_headers['Referer'] = client_referer

        if PROXY_VERBOSE:
            print(f"  VERBOSE: Bước 1 - Truy cập URL ban đầu: {target_url}")
        
        initial_response = scraper.get(target_url, headers=initial_request_headers, allow_redirects=True, stream=True)
        response_for_content = initial_response # Mặc định là response ban đầu

        if PROXY_VERBOSE:
            print(f"  VERBOSE: Bước 1 - Status: {initial_response.status_code}, URL cuối: {initial_response.url}")

        initial_response_headers = dict(initial_response.headers)
        current_url_after_step1 = initial_response.url
        
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
            try:
                final_response = scraper.get(final_url_from_header, headers=final_request_headers, allow_redirects=True, stream=True)
                if initial_response: # Đóng response cũ nếu không dùng nữa
                    initial_response.close()
                response_for_content = final_response
                if PROXY_VERBOSE:
                    print(f"  VERBOSE: Bước 2 - Status: {final_response.status_code}, URL cuối: {final_response.url}")
            except requests.exceptions.RequestException as e_final:
                if initial_response: initial_response.close()
                error_msg = f"REQUEST_LIB_ERROR: Bước 2 thất bại khi truy cập '{final_url_from_header}': {str(e_final)}"
                print(error_msg)
                err_content = e_final.response.content if e_final.response else None
                err_content_type = e_final.response.headers.get('Content-Type', 'text/plain') if e_final.response else 'text/plain'
                err_status_code = e_final.response.status_code if e_final.response else 503
                if e_final.response: e_final.response.close()
                raise ProxyFetchError(error_msg, status_code=err_status_code, content=err_content, content_type=err_content_type) from e_final
        
        # response_for_content bây giờ là đối tượng response cuối cùng cần trả về
        # Không đọc .content ở đây, mà trả về cả object response để handler xử lý stream
        if PROXY_VERBOSE:
            print(f"  Sẵn sàng stream từ '{response_for_content.url}' (Status: {response_for_content.status_code}, Type: {response_for_content.headers.get('Content-Type')})")
        return response_for_content

    except requests.exceptions.RequestException as e_req:
        if initial_response: initial_response.close()
        if response_for_content and response_for_content != initial_response : response_for_content.close() # Đảm bảo response_for_content cũng được đóng nếu nó khác initial_response và có lỗi xảy ra sau khi nó được gán từ final_response

        error_msg = f"REQUEST_LIB_ERROR: Lỗi trong quá trình request tới '{target_url}': {str(e_req)}"
        print(error_msg)
        # print(traceback.format_exc()) # Bỏ comment nếu cần debug sâu
        
        err_content = e_req.response.content if e_req.response else None
        err_content_type = e_req.response.headers.get('Content-Type', 'text/plain') if e_req.response else 'text/plain'
        err_status_code = e_req.response.status_code if e_req.response else 503 # Service Unavailable
        if e_req.response: e_req.response.close()
        raise ProxyFetchError(error_msg, status_code=err_status_code, content=err_content, content_type=err_content_type) from e_req
    
    except Exception as e: # Các lỗi không mong muốn khác
        if initial_response: initial_response.close()
        if response_for_content and response_for_content != initial_response : response_for_content.close()

        error_msg = f"CRITICAL_ERROR: Lỗi không xác định khi xử lý '{target_url}': {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        raise ProxyFetchError(error_msg, status_code=500) from e

# Route handler được chuyển thành async và sử dụng StreamingResponse
@app.get("/", response_class=StreamingResponse) # response_class có thể không cần thiết khi trả về StreamingResponse trực tiếp
async def proxy_handler(
    request: Request,
    url: Optional[str] = Query(None, description="URL cần proxy truy cập"),
    referer: Optional[str] = Query(None, description="Referer header tùy chọn cho request đến target URL"),
    auth_token: Optional[str] = Query(None, description="API key gửi qua query parameter"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API key gửi qua header")
):
    # --- Xác thực API Key (logic tương tự Flask, giữ nguyên) ---
    if EXPECTED_API_KEY:
        actual_client_api_key = x_api_key or auth_token
        auth_method = "N/A"
        if x_api_key: auth_method = "header 'X-API-Key'"
        elif auth_token: auth_method = "query param 'auth_token'"

        if not actual_client_api_key:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. Thiếu API key. IP: {request.client.host if request.client else 'N/A'}")
            raise HTTPException(status_code=401, detail="Lỗi: Thiếu API key.")
        
        if actual_client_api_key != EXPECTED_API_KEY:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. API Key không hợp lệ (phương thức: {auth_method}). IP: {request.client.host if request.client else 'N/A'}")
            raise HTTPException(status_code=403, detail="Lỗi: API key không hợp lệ.")
        
        if PROXY_VERBOSE:
            print(f"AUTH_SUCCESS: API Key hợp lệ (phương thức: {auth_method}). IP: {request.client.host if request.client else 'N/A'}")
    # --- Kết thúc xác thực API Key ---

    if not url:
        raise HTTPException(status_code=400, detail="Lỗi: Thiếu tham số 'url'. Cách dùng: /?url=<URL_CẦN_TRUY_CẬP>")

    target_response: Optional[requests.Response] = None
    try:
        # Chạy hàm blocking `fetch_target_response` trong một thread riêng
        target_response = await asyncio.to_thread(fetch_target_response, url, referer)

        # Generator để stream content
        async def content_streamer() -> AsyncGenerator[bytes, None]:
            try:
                async for chunk in target_response.iter_content(chunk_size=8192): # 8KB chunks
                    if chunk: # filter out keep-alive new chunks
                        yield chunk
            except Exception as e_stream:
                print(f"STREAM_ERROR: Lỗi khi đang stream content từ {target_response.url if target_response else 'N/A'}: {e_stream}")
                # Có thể raise một exception ở đây nếu muốn client biết stream bị lỗi giữa chừng
            finally:
                if target_response:
                    target_response.close() # Quan trọng: đóng response để giải phóng connection

        # Proxy các header cần thiết từ target response
        # Cẩn thận không proxy các header gây lỗi (ví dụ 'Transfer-Encoding')
        # FastAPI/Uvicorn sẽ tự xử lý Content-Length và Content-Encoding (như gzip) khi stream.
        response_headers = {}
        if target_response.headers.get('Content-Type'):
            response_headers['Content-Type'] = target_response.headers['Content-Type']
        
        # Ví dụ: Lấy một số header an toàn khác để proxy
        safe_headers_to_proxy = ['cache-control', 'etag', 'last-modified', 'expires', 'pragma', 'content-disposition']
        # Thêm header 'Zr-Final-Url' nếu có trong response gốc, vì nó là custom header từ logic cũ
        if 'Zr-Final-Url' in target_response.headers:
             response_headers['Zr-Final-Url'] = target_response.headers['Zr-Final-Url']

        for h_name, h_val in target_response.headers.items():
            if h_name.lower() in safe_headers_to_proxy:
                response_headers[h_name] = h_val
        
        # Nếu URL cuối cùng khác URL request, có thể thêm header này cho client biết
        if target_response.url != url:
            response_headers['X-Final-Url'] = target_response.url


        return StreamingResponse(
            content_streamer(),
            status_code=target_response.status_code,
            headers=response_headers
            # media_type đã được set trong response_headers['Content-Type']
        )

    except ProxyFetchError as e_fetch:
        if target_response: target_response.close() # Đảm bảo đóng nếu có lỗi xảy ra sau khi lấy được response
        # Trả về FastAPIResponse với nội dung lỗi từ ProxyFetchError
        # (có thể là trang lỗi từ server đích hoặc thông báo lỗi nội bộ)
        return FastAPIResponse(content=e_fetch.content, status_code=e_fetch.status_code, media_type=e_fetch.content_type)
    
    except Exception as e_handler: # Bắt các lỗi không mong muốn khác trong handler
        if target_response: target_response.close()
        print(f"HANDLER_ERROR: Lỗi không xác định trong proxy_handler cho {url}: {str(e_handler)}")
        print(traceback.format_exc())
        # Không nên trả về traceback cho client, chỉ một thông báo lỗi chung
        raise HTTPException(status_code=500, detail=f"Lỗi máy chủ proxy nội bộ.")


if __name__ == '__main__':
    print(f"FastAPI Proxy server (Optimized, chạy trực tiếp với Uvicorn) đang khởi động trên http://0.0.0.0:{APP_LISTEN_PORT}")
    if EXPECTED_API_KEY:
        print(f"  API Key Authentication IS ENABLED.")
    else:
        print(f"  WARNING: API Key Authentication IS DISABLED. Proxy đang mở.")
    
    if PROXY_VERBOSE:
        print("  VERBOSE logging is ENABLED.")
    else:
        print("  VERBOSE logging is DISABLED.")
    
    # Khi deploy production, reload nên là False.
    # Cân nhắc sử dụng Gunicorn làm process manager cho Uvicorn workers để tận dụng đa nhân CPU.
    # Ví dụ: gunicorn -w 4 -k uvicorn.workers.UvicornWorker proxy_server:app -b 0.0.0.0:5000
    # Tham số `workers` của uvicorn.run chỉ hoạt động khi reload=False.
    dev_mode = os.environ.get("DEV_MODE", "false").lower() == "true"
    uvicorn_workers = int(os.environ.get("UVICORN_WORKERS", "1"))

    if dev_mode:
        print("  Chạy ở chế độ DEV_MODE (reload=True, workers=1).")
        uvicorn.run("proxy_server:app", host="0.0.0.0", port=APP_LISTEN_PORT, reload=True)
    else:
        print(f"  Chạy ở chế độ PRODUCTION (reload=False, workers={uvicorn_workers}).")
        uvicorn.run("proxy_server:app", host="0.0.0.0", port=APP_LISTEN_PORT, reload=False, workers=uvicorn_workers)

from flask import Flask, request, Response
import cloudscraper
import os
import traceback

app = Flask(__name__)

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
# --- Kết Thúc Đọc Cấu Hình ---

# (Hàm get_socks_proxy_settings và fetch_final_content_from_url giữ nguyên như trước)
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

# (Các phần khác của file giữ nguyên)

def fetch_final_content_from_url(target_url, client_referer=None):
    active_proxies = get_socks_proxy_settings()
    log_prefix = f"Proxying '{target_url}'"
    if client_referer:
        log_prefix += f" (Referer: '{client_referer}')"
    # Thông báo về SOCKS5 sẽ được in bên dưới sau khi scraper được tạo và proxies được gán (nếu có)
    
    print(log_prefix) # Log thông tin cơ bản của request

    # Bước 1: Tạo scraper trước mà không có argument 'proxies'
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        # debug=PROXY_VERBOSE # Bạn có thể bật debug của cloudscraper dựa trên PROXY_VERBOSE nếu muốn
    )

    # Bước 2: Gán proxies cho scraper SAU KHI nó được tạo (nếu có cấu hình SOCKS5)
    if active_proxies:
        scraper.proxies = active_proxies
        print(f"  SOCKS5 Proxy configured for this request: {active_proxies.get('http')}")
    elif PROXY_VERBOSE: # Chỉ in nếu verbose và không có SOCKS
        print("  No SOCKS5 Proxy configured for this request.")


    # Phần còn lại của hàm giữ nguyên...
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
        # ... (phần còn lại của hàm không thay đổi) ...
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
            if PROXY_VERBOSE: # Chỉ log thành công chi tiết nếu bật verbose
                print(f"  SUCCESS: '{target_url}' -> '{final_url_accessed}' (Status: {final_status_code}, Type: {content_type})")
            return content, content_type, final_status_code, None
        else:
            error_msg = f"ERROR: Target URL '{final_url_accessed}' responded with {final_status_code} - {response_for_content.reason} (Original URL: '{target_url}')"
            print(error_msg) # Luôn log lỗi này
            return response_for_content.content, \
                   response_for_content.headers.get('Content-Type', 'text/plain'), \
                   final_status_code, \
                   error_msg # Trả về error_msg để client có thể nhận được nếu cần

    except Exception as e:
        error_msg = f"CRITICAL_ERROR: Exception while processing '{target_url}': {str(e)}"
        print(error_msg) # Luôn log lỗi nghiêm trọng
        print(traceback.format_exc()) # Luôn in traceback để debug
        return None, None, 500, error_msg


@app.route('/')
def proxy_handler():
    # --- Xác thực API Key ---
    if EXPECTED_API_KEY: # Chỉ xác thực nếu PROXY_API_KEY được cấu hình trên server
        client_api_key_from_header = request.headers.get('X-API-Key')
        # Sử dụng một tên query parameter khác cho API key, ví dụ 'auth_token' hoặc 'proxy_key'
        client_api_key_from_query = request.args.get('auth_token') 

        # Ưu tiên API key từ header nếu có, nếu không thì lấy từ query parameter
        actual_client_api_key = client_api_key_from_header or client_api_key_from_query
        
        auth_method = "N/A"
        if client_api_key_from_header:
            auth_method = "header 'X-API-Key'"
        elif client_api_key_from_query:
            auth_method = "query param 'auth_token'"

        if not actual_client_api_key:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. Thiếu API key. IP: {request.remote_addr}")
            return Response("Lỗi: Thiếu API key. Vui lòng cung cấp 'X-API-Key' header hoặc 'auth_token' query parameter.", status=401, mimetype='text/plain')
        
        if actual_client_api_key != EXPECTED_API_KEY:
            print(f"AUTH_FAIL: Yêu cầu bị từ chối. API Key không hợp lệ (phương thức: {auth_method}). IP: {request.remote_addr}, Key: '{actual_client_api_key[:10]}...'")
            return Response("Lỗi: API key không hợp lệ.", status=403, mimetype='text/plain')
        
        if PROXY_VERBOSE:
            print(f"AUTH_SUCCESS: API Key hợp lệ (phương thức: {auth_method}). IP: {request.remote_addr}")
    # --- Kết thúc xác thực API Key ---

    # Lấy URL mục tiêu (không phải là API key)
    target_url = request.args.get('url') 
    client_referer = request.args.get('referer')

    if not target_url:
        return Response("Lỗi: Thiếu tham số 'url'. Cách dùng: /?url=<URL_CẦN_TRUY_CẬP>", status=400, mimetype='text/plain')

    content, content_type, status_code, error_message = fetch_final_content_from_url(target_url, client_referer)

    if error_message and not content:
         return Response(error_message, status=status_code or 500, mimetype='text/plain')
    
    return Response(content, status=status_code or 200, mimetype=content_type)

if __name__ == '__main__':
    print(f"Proxy server (chạy trực tiếp, không qua Gunicorn) đang khởi động trên http://0.0.0.0:{APP_LISTEN_PORT}")
    if EXPECTED_API_KEY:
        print(f"  API Key Authentication IS ENABLED. Client cần cung cấp 'X-API-Key' header hoặc 'auth_token' query parameter.")
    else:
        print(f"  WARNING: API Key Authentication IS DISABLED. Proxy đang mở. (PROXY_API_KEY chưa được thiết lập)")
    
    if PROXY_VERBOSE:
        print("  VERBOSE logging is ENABLED.")
    else:
        print("  VERBOSE logging is DISABLED. Set PROXY_VERBOSE_LOGGING=true to enable.")
    app.run(host='0.0.0.0', port=APP_LISTEN_PORT, debug=False)

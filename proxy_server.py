from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
from typing import Optional
import os
import traceback
import cloudscraper

# --- Cấu hình ---
SOCKS5_PROXY_HOST = os.getenv("SOCKS5_PROXY_HOST")
SOCKS5_PROXY_PORT = int(os.getenv("SOCKS5_PROXY_PORT", "0")) or None
SOCKS5_USERNAME = os.getenv("SOCKS5_USERNAME")
SOCKS5_PASSWORD = os.getenv("SOCKS5_PASSWORD")
APP_LISTEN_PORT = int(os.getenv("APP_PORT", "5000"))
PROXY_VERBOSE = os.getenv("PROXY_VERBOSE_LOGGING", "false").lower() == "true"
EXPECTED_API_KEY = os.getenv("PROXY_API_KEY")
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

app = FastAPI(title="Cloudscraper Proxy API", version="1.1.0")

# --- Proxy setting ---
def get_socks_proxy_settings():
    if SOCKS5_PROXY_HOST and SOCKS5_PROXY_PORT:
        auth = f"{SOCKS5_USERNAME}:{SOCKS5_PASSWORD}@" if SOCKS5_USERNAME and SOCKS5_PASSWORD else ""
        proxy_url = f"socks5h://{auth}{SOCKS5_PROXY_HOST}:{SOCKS5_PROXY_PORT}"
        return {"http": proxy_url, "https": proxy_url}
    return None

# --- Core fetching logic ---
def fetch_url(target_url: str, referer: Optional[str] = None):
    proxies = get_socks_proxy_settings()

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )
    if proxies:
        scraper.proxies = proxies

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'close'  # hạn chế giữ kết nối
    }
    if referer:
        headers['Referer'] = referer

    try:
        response = scraper.get(target_url, headers=headers, allow_redirects=True, timeout=15)
        if response.status_code == 200:
            return response.content, response.headers.get("Content-Type", "application/octet-stream"), 200, None
        return response.content, "text/plain", response.status_code, f"Upstream error {response.status_code}"
    except Exception as e:
        traceback.print_exc()
        return None, None, 500, f"Internal error: {str(e)}"

# --- Proxy route ---
@app.get("/", response_class=FastAPIResponse)
def proxy_handler(
    request: Request,
    url: Optional[str] = Query(None, description="URL cần truy cập"),
    referer: Optional[str] = Query(None, description="Tùy chọn Referer"),
    auth_token: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    # Xác thực API Key nếu yêu cầu
    if EXPECTED_API_KEY:
        key = x_api_key or auth_token
        if not key:
            raise HTTPException(status_code=401, detail="Thiếu API key.")
        if key != EXPECTED_API_KEY:
            raise HTTPException(status_code=403, detail="API key không hợp lệ.")

    if not url:
        raise HTTPException(status_code=400, detail="Thiếu tham số 'url'.")

    content, content_type, status_code, error = fetch_url(url, referer)

    if error and not content:
        raise HTTPException(status_code=status_code, detail=error)

    return FastAPIResponse(content=content, status_code=status_code, media_type=content_type)

# --- Local run ---
if __name__ == "__main__":
    import uvicorn
    print(f"🔗 Running at http://0.0.0.0:{APP_LISTEN_PORT}")
    uvicorn.run("proxy_server:app", host="0.0.0.0", port=APP_LISTEN_PORT, reload=DEV_MODE)

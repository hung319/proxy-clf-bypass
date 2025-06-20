import os
import json # <--- Thêm import json
import logging
from contextlib import asynccontextmanager
from typing import Optional, List

import cloudscraper
from fastapi import FastAPI, Request, Response as FastAPIResponse, Query, HTTPException
from pydantic import BaseModel
from pydantic_settings import BaseSettings

# --- Cấu hình (Không đổi) ---
class Settings(BaseSettings):
    app_port: int = 5000
    dev_mode: bool = False
    proxy_verbose_logging: bool = False
    expected_api_key: Optional[str] = None
    socks5_proxy_host: Optional[str] = None
    socks5_proxy_port: Optional[int] = None
    socks5_username: Optional[str] = None
    socks5_password: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

settings = Settings()
logging.basicConfig(level=logging.INFO if not settings.proxy_verbose_logging else logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Quản lý vòng đời ứng dụng (Không đổi) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Creating a reusable cloudscraper instance...")
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )
    if settings.socks5_proxy_host and settings.socks5_proxy_port:
        auth = f"{settings.socks5_username}:{settings.socks5_password}@" if settings.socks5_username and settings.socks5_password else ""
        proxy_url = f"socks5h://{auth}{settings.socks5_proxy_host}:{settings.socks5_proxy_port}"
        scraper.proxies = {"http": proxy_url, "https": proxy_url}
        logger.info(f"Cloudscraper is configured to use SOCKS5 proxy: {settings.socks5_proxy_host}")
    app.state.scraper = scraper
    yield
    logger.info("Closing cloudscraper session.")
    app.state.scraper.close()

# --- Khởi tạo FastAPI app ---
app = FastAPI(
    title="Advanced Cloudscraper Proxy API", 
    version="3.0.0", # <--- Cập nhật phiên bản
    lifespan=lifespan
)

# --- Models (Không đổi) ---
class StatusResponse(BaseModel):
    status: str
    message: str

# --- API Endpoints ---

@app.get("/status", response_model=StatusResponse, tags=["Server Status"])
async def get_server_status():
    return {"status": "ok", "message": "Server is up and running!"}

# --- ĐÃ NÂNG CẤP: Hỗ trợ GET và POST trên cùng một route ---
@app.api_route("/", methods=["GET", "POST"], response_class=FastAPIResponse, tags=["Proxy"])
async def proxy_handler(
    request: Request,
    url: str = Query(..., description="URL to proxy"),
    key: Optional[str] = Query(None, description="API Key for access"),
    referer: Optional[str] = Query(None, description="Optional Referer header"),
    # --- THÊM MỚI: Tham số nhận headers tùy chỉnh ---
    custom_headers: Optional[str] = Query(None, alias="headers", description="URL-encoded JSON string of custom headers")
):
    # Xác thực API Key (không đổi)
    if settings.expected_api_key:
        if key is None:
            raise HTTPException(status_code=401, detail="API Key is missing. Please add '&key=YOUR_KEY'.")
        if key != settings.expected_api_key:
            raise HTTPException(status_code=403, detail="Invalid API Key.")

    scraper_instance = request.app.state.scraper
    method = request.method
    
    # --- THÊM MỚI: Đọc body của request nếu là POST ---
    body = await request.body() if method == "POST" else None
    
    # Lấy Content-Type từ request gốc để chuyển tiếp
    original_content_type = request.headers.get("Content-Type")

    content, content_type = await fetch_url_content(
        scraper=scraper_instance,
        target_url=url,
        method=method,
        referer=referer,
        body=body,
        custom_headers_json=custom_headers,
        original_content_type=original_content_type
    )

    return FastAPIResponse(content=content, media_type=content_type)


# --- ĐÃ NÂNG CẤP: Logic xử lý chính hỗ trợ GET/POST và custom headers ---
async def fetch_url_content(
    scraper: cloudscraper.CloudScraper, 
    target_url: str, 
    method: str,
    referer: Optional[str] = None,
    body: Optional[bytes] = None,
    custom_headers_json: Optional[str] = None,
    original_content_type: Optional[str] = None
):
    # Headers mặc định
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    if referer:
        headers['Referer'] = referer

    # --- THÊM MỚI: Xử lý headers tùy chỉnh ---
    if custom_headers_json:
        try:
            # Ghi đè headers mặc định bằng headers người dùng cung cấp
            headers.update(json.loads(custom_headers_json))
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format in 'headers' parameter.")

    # Nếu là POST, ưu tiên Content-Type từ request gốc
    if method == "POST" and original_content_type:
        headers['Content-Type'] = original_content_type
        
    try:
        if method == "GET":
            response = scraper.get(target_url, headers=headers, allow_redirects=True, timeout=20)
        elif method == "POST":
            response = scraper.post(target_url, headers=headers, data=body, allow_redirects=True, timeout=20)
        else:
            raise HTTPException(status_code=405, detail=f"Method '{method}' not supported.")
            
        response.raise_for_status()
        return response.content, response.headers.get("Content-Type", "application/octet-stream")

    except Exception as e:
        logger.error(f"Error fetching {target_url} with method {method}: {e}", exc_info=settings.proxy_verbose_logging)
        raise HTTPException(status_code=502, detail=f"Failed to fetch upstream URL. Error: {e}")

# --- Local run (Không đổi) ---
if __name__ == "__main__":
    import uvicorn
    logger.info(f"🚀 Starting server in {'DEV_MODE' if settings.dev_mode else 'PROD_MODE'} at http://0.0.0.0:{settings.app_port}")
    uvicorn.run(
        "__main__:app", 
        host="0.0.0.0", 
        port=settings.app_port, 
        reload=settings.dev_mode
    )

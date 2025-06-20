import os
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

import cloudscraper
from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
from pydantic import BaseModel
from pydantic_settings import BaseSettings

# --- Cấu hình tập trung bằng Pydantic ---
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

# Khởi tạo settings
settings = Settings()

# Cấu hình logging
logging.basicConfig(level=logging.INFO if not settings.proxy_verbose_logging else logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Quản lý vòng đời ứng dụng với Lifespan ---
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

# Khởi tạo FastAPI app với lifespan
app = FastAPI(
    title="Enhanced Cloudscraper Proxy API",
    version="2.2.0",
    lifespan=lifespan
)

# --- Model cho response của status ---
class StatusResponse(BaseModel):
    status: str
    message: str

# --- API Endpoint ---

@app.get("/status", response_model=StatusResponse, tags=["Server Status"])
async def get_server_status():
    """
    Cung cấp trạng thái hoạt động của máy chủ.
    """
    return {"status": "ok", "message": "Server is up and running!"}

@app.api_route("/", methods=["GET", "POST"], response_class=FastAPIResponse, tags=["Proxy"])
async def proxy_handler(
    request: Request,
    url: str = Query(..., description="URL to proxy"),
    # --- THAY ĐỔI 1: Thêm lại tham số referer ---
    referer: Optional[str] = Query(None, description="Shortcut to set the 'Referer' header. Overwrites 'Referer' from custom headers if provided."),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    # --- THAY ĐỔI 2: Cập nhật docstring để giải thích về custom headers ---
    """
    Proxy an HTTP request to a target URL using cloudscraper to bypass Cloudflare.

    This endpoint supports both **GET** and **POST** methods.

    ### Custom Headers
    Most headers from your original request will be automatically forwarded to the target URL. 
    This allows you to send custom headers like `Authorization`, `Cookie`, etc.

    The following headers are managed by the proxy and will be excluded from forwarding:
    - `host`
    - `user-agent` (managed by cloudscraper)
    - `accept-encoding`
    - `connection`
    - `x-api-key`
    - `content-length` (recalculated automatically)
    - `content-type` (handled separately for POST)
    """
    if settings.expected_api_key and x_api_key != settings.expected_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key.")

    scraper_instance = request.app.state.scraper
    
    request_body = await request.body() if request.method == "POST" else None

    headers_to_forward = {}
    excluded_headers = [
        "host", "user-agent", "accept-encoding", "connection", 
        "x-api-key", "content-length", "content-type", "referer" # Exclude referer here, will handle it separately
    ]
    for name, value in request.headers.items():
        if name.lower() not in excluded_headers:
            headers_to_forward[name] = value

    if request.method == "POST" and "content-type" in request.headers:
        headers_to_forward["Content-Type"] = request.headers["content-type"]
        
    # --- THAY ĐỔI 3: Gán giá trị referer từ query param, ưu tiên nó ---
    if referer:
        headers_to_forward["Referer"] = referer
    
    content, content_type, status_code = await fetch_url_content(
        scraper=scraper_instance,
        method=request.method,
        target_url=url,
        custom_headers=headers_to_forward,
        post_data=request_body
    )
    
    return FastAPIResponse(content=content, media_type=content_type, status_code=status_code)

async def fetch_url_content(
    scraper: cloudscraper.CloudScraper, 
    method: str,
    target_url: str, 
    custom_headers: Dict[str, Any],
    post_data: Optional[bytes] = None
):
    base_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    final_headers = {**base_headers, **custom_headers}
    
    logger.debug(f"Forwarding {method} request to {target_url} with headers: {final_headers}")
    if post_data:
        logger.debug(f"Forwarding POST data: {post_data[:200]}...")

    try:
        response = scraper.request(
            method,
            target_url, 
            headers=final_headers, 
            data=post_data,
            allow_redirects=True, 
            timeout=20
        )
        response.raise_for_status()

        return (
            response.content, 
            response.headers.get("Content-Type", "application/octet-stream"),
            response.status_code
        )

    except Exception as e:
        logger.error(f"Error fetching {target_url}: {e}", exc_info=settings.proxy_verbose_logging)
        raise HTTPException(status_code=502, detail=f"Failed to fetch upstream URL. Error: {str(e)}")

# --- Local run ---
if __name__ == "__main__":
    import uvicorn
    logger.info(f"🚀 Starting server in DEV_MODE at http://0.0.0.0:{settings.app_port}")
    uvicorn.run(
        "__main__:app", 
        host="0.0.0.0", 
        port=settings.app_port, 
        reload=settings.dev_mode
    )

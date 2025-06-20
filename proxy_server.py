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
    # Cài đặt ứng dụng
    app_port: int = 5000
    dev_mode: bool = False
    proxy_verbose_logging: bool = False
    expected_api_key: Optional[str] = None
    
    # Cài đặt SOCKS5 Proxy
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
    version="2.1.0",
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

# --- THAY ĐỔI 1: Sử dụng api_route để chấp nhận cả GET và POST ---
@app.api_route("/", methods=["GET", "POST"], response_class=FastAPIResponse)
async def proxy_handler(
    request: Request,
    url: str = Query(..., description="URL to proxy"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    # Xác thực API Key
    if settings.expected_api_key and x_api_key != settings.expected_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key.")

    # Lấy scraper đã được tạo sẵn từ app state
    scraper_instance = request.app.state.scraper
    
    # --- THAY ĐỔI 2: Xử lý request body và custom headers ---
    # Lấy request body nếu phương thức là POST
    request_body = await request.body() if request.method == "POST" else None

    # Lấy và lọc các headers từ request gốc để chuyển tiếp
    headers_to_forward = {}
    # Các header không nên chuyển tiếp trực tiếp
    excluded_headers = [
        "host", "user-agent", "accept-encoding", "connection", 
        "x-api-key", "content-length", "content-type"
    ]
    for name, value in request.headers.items():
        if name.lower() not in excluded_headers:
            headers_to_forward[name] = value

    # Lấy content-type từ header gốc nếu là POST request
    if request.method == "POST" and "content-type" in request.headers:
        headers_to_forward["Content-Type"] = request.headers["content-type"]
    
    content, content_type, status_code = await fetch_url_content(
        scraper=scraper_instance,
        method=request.method,
        target_url=url,
        custom_headers=headers_to_forward,
        post_data=request_body
    )
    
    # Trả về response với status code gốc
    return FastAPIResponse(content=content, media_type=content_type, status_code=status_code)


# --- THAY ĐỔI 3: Nâng cấp hàm xử lý chính để hỗ trợ các phương thức và header khác nhau ---
async def fetch_url_content(
    scraper: cloudscraper.CloudScraper, 
    method: str,
    target_url: str, 
    custom_headers: Dict[str, Any],
    post_data: Optional[bytes] = None
):
    # Các header mặc định, sẽ bị ghi đè bởi custom_headers nếu trùng lặp
    base_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    # Gộp header mặc định và header tùy chỉnh
    final_headers = {**base_headers, **custom_headers}
    
    logger.debug(f"Forwarding {method} request to {target_url} with headers: {final_headers}")
    if post_data:
        logger.debug(f"Forwarding POST data: {post_data[:200]}...") # Log một phần body

    try:
        # Sử dụng scraper.request để có thể gọi bất kỳ phương thức nào (GET, POST, ...)
        response = scraper.request(
            method,
            target_url, 
            headers=final_headers, 
            data=post_data,
            allow_redirects=True, 
            timeout=20
        )
        response.raise_for_status()

        # Trả về cả status code để proxy có thể trả về chính xác hơn
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

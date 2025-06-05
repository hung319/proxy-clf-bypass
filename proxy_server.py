import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

import cloudscraper
from fastapi import FastAPI, Request, Response as FastAPIResponse, Header, Query, HTTPException
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
        # Tự động đọc biến môi trường, không phân biệt chữ hoa/thường
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

# Khởi tạo settings
settings = Settings()

# Cấu hình logging
logging.basicConfig(level=logging.INFO if not settings.proxy_verbose_logging else logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Quản lý vòng đời ứng dụng với Lifespan ---
# Tạo một context manager để khởi tạo và giải phóng tài nguyên
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi động: Tạo một scraper instance duy nhất
    logger.info("Creating a reusable cloudscraper instance...")
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )
    
    # Cấu hình proxy cho scraper nếu có
    if settings.socks5_proxy_host and settings.socks5_proxy_port:
        auth = f"{settings.socks5_username}:{settings.socks5_password}@" if settings.socks5_username and settings.socks5_password else ""
        proxy_url = f"socks5h://{auth}{settings.socks5_proxy_host}:{settings.socks5_proxy_port}"
        scraper.proxies = {"http": proxy_url, "https": proxy_url}
        logger.info(f"Cloudscraper is configured to use SOCKS5 proxy: {settings.socks5_proxy_host}")
    
    # Gán scraper vào state của app để tái sử dụng
    app.state.scraper = scraper
    
    yield
    
    # Shutdown: Dọn dẹp (ví dụ: đóng session)
    logger.info("Closing cloudscraper session.")
    app.state.scraper.close()

# Khởi tạo FastAPI app với lifespan
app = FastAPI(
    title="Optimized Cloudscraper Proxy API", 
    version="2.0.0",
    lifespan=lifespan
)

# --- Logic xử lý chính ---
async def fetch_url_content(
    scraper: cloudscraper.CloudScraper, 
    target_url: str, 
    referer: Optional[str] = None
):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        # Bỏ 'Connection': 'close' để tận dụng keep-alive, tăng tốc độ cho các request liên tiếp
    }
    if referer:
        headers['Referer'] = referer

    try:
        # FastAPI sẽ tự động chạy hàm đồng bộ này trong một thread pool
        # mà không block event loop chính, nhờ đó vẫn xử lý được nhiều request
        response = scraper.get(target_url, headers=headers, allow_redirects=True, timeout=20)
        response.raise_for_status()  # Ném lỗi cho các status code 4xx/5xx

        return response.content, response.headers.get("Content-Type", "application/octet-stream")

    except Exception as e:
        logger.error(f"Error fetching {target_url}: {e}", exc_info=settings.proxy_verbose_logging)
        # Ném lại lỗi để endpoint có thể xử lý và trả về status code phù hợp
        raise HTTPException(status_code=502, detail=f"Failed to fetch upstream URL. Error: {e}")

# --- API Endpoint ---
@app.get("/", response_class=FastAPIResponse)
async def proxy_handler(
    request: Request,
    url: str = Query(..., description="URL to proxy"), # Dùng ... để yêu cầu tham số là bắt buộc
    referer: Optional[str] = Query(None, description="Optional Referer header"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    # Xác thực API Key
    if settings.expected_api_key and x_api_key != settings.expected_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key.")

    # Lấy scraper đã được tạo sẵn từ app state
    scraper_instance = request.app.state.scraper
    
    content, content_type = await fetch_url_content(scraper_instance, url, referer)

    return FastAPIResponse(content=content, media_type=content_type)

# --- Local run ---
if __name__ == "__main__":
    import uvicorn
    logger.info(f"🚀 Starting server in DEV_MODE at http://0.0.0.0:{settings.app_port}")
    uvicorn.run(
        "proxy_server:app", 
        host="0.0.0.0", 
        port=settings.app_port, 
        reload=settings.dev_mode
    )

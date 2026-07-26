import uvicorn
from src.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "src.webhook:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )

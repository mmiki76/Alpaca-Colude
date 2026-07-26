from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    binance_api_key: str
    binance_api_secret: str
    binance_testnet: bool = True
    webhook_secret: str
    host: str = "0.0.0.0"
    port: int = 8080
    order_size_usdt: float = 10.0
    leverage: int = 1
    market_type: str = "SPOT"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

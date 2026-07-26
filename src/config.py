from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Exchange: binance sau mexc
    exchange: str = "mexc"
    api_key: str
    api_secret: str
    testnet: bool = False
    webhook_secret: str
    host: str = "0.0.0.0"
    port: int = 8080
    order_size_usdt: float = 20.0
    leverage: int = 1
    # SPOT sau FUTURES
    market_type: str = "FUTURES"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

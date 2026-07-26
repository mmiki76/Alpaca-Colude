import httpx
from loguru import logger


async def send_telegram(token: str, chat_id: str, message: str) -> None:
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning(f"Telegram eroare: {resp.text}")
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")


def format_order_message(action: str, symbol: str, quantity: float, price: float,
                          order_id: str, balance_usdt: float = None) -> str:
    emoji = "🟢" if action == "BUY" else "🔴"
    msg = (
        f"{emoji} <b>{action} executat</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 Pereche: <b>{symbol}</b>\n"
        f"💰 Cantitate: <b>{quantity}</b>\n"
        f"💵 Pret: <b>{price:.4f} USDT</b>\n"
        f"🆔 Order ID: <code>{order_id}</code>\n"
    )
    if balance_usdt is not None:
        msg += f"━━━━━━━━━━━━━━\n💼 Sold USDT: <b>{balance_usdt:.2f} USDT</b>\n"
    return msg


def format_error_message(action: str, symbol: str, error: str) -> str:
    return (
        f"⚠️ <b>EROARE la {action} {symbol}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"❌ {error}"
    )


def format_status_message(symbol: str, price: float, balance_usdt: float) -> str:
    from datetime import datetime
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"📋 <b>Raport periodic Clode</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🕐 {now}\n"
        f"📊 Pereche: <b>{symbol}</b>\n"
        f"💵 Pret curent: <b>{price:.4f} USDT</b>\n"
        f"💼 Sold USDT: <b>{balance_usdt:.2f} USDT</b>\n"
        f"✅ Bot activ"
    )

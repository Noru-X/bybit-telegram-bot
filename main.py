import os
import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters
)

# =============================
# BOT TOKEN
# =============================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

# =============================
# HTTP 설정 (Railway 안정화)
# =============================
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}

def safe_get(url, params):
    for _ in range(2):  # 최대 2번 시도
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=10)
            if r.status_code == 200 and r.text:
                return r
        except:
            pass
    return None

# =============================
# 가격 포맷
# =============================
def format_price(price):
    if price >= 1000:
        return f"{price:,.0f}"
    elif price >= 1:
        return f"{price:,.2f}"
    else:
        return f"{price:,.6f}"

# =============================
# UTC 00:00 기준가
# =============================
def get_utc0_price(symbol):
    now = datetime.now(timezone.utc)
    utc_0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now < utc_0:
        utc_0 -= timedelta(days=1)

    start = int(utc_0.timestamp() * 1000)

    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": "1",
        "start": start,
        "limit": 1
    }

    r = safe_get(url, params)
    if not r:
        return None

    data = r.json()
    if not data.get("result") or not data["result"].get("list"):
        return None

    return float(data["result"]["list"][0][1])

# =============================
# 현재 시세
# =============================
def get_coin_data(coin):
    symbol = coin.upper() + "USDT"
    url = "https://api.bybit.com/v5/market/tickers"
    params = {"category": "linear", "symbol": symbol}

    r = safe_get(url, params)
    if not r:
        print(f"[PRICE ERROR] {symbol} : Empty response")
        return None, None, None

    data = r.json()
    if not data.get("result") or not data["result"].get("list"):
        print(f"[PRICE ERROR] {symbol} : Invalid response")
        return None, None, None

    info = data["result"]["list"][0]
    price = float(info["lastPrice"])
    funding = float(info["fundingRate"]) * 100

    base = get_utc0_price(symbol)
    if base is None:
        return None, None, None

    percent = ((price - base) / base) * 100
    return price, percent, funding

# =============================
# 4H 캔들
# =============================
def get_4h_candles(symbol, limit=100):
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": "240",
        "limit": limit
    }

    r = safe_get(url, params)
    if not r:
        return None

    data = r.json()
    if not data.get("result") or not data["result"].get("list"):
        return None

    return data["result"]["list"]

# =============================
# 지지 / 저항
# =============================
def calc_sr(candles, current):
    cluster = defaultdict(float)
    step = current * 0.005

    for c in candles:
        high = float(c[2])
        low = float(c[3])
        vol = float(c[5])
        mid = (high + low) / 2
        key = round(mid / step) * step
        cluster[key] += vol * 1.5

    levels = sorted(cluster.items(), key=lambda x: x[1], reverse=True)

    supports, resistances = [], []
    for price, _ in levels:
        if price < current:
            if all(abs(price - s) > step for s in supports):
                supports.append(price)
        else:
            if all(abs(price - r) > step for r in resistances):
                resistances.append(price)
        if len(supports) >= 3 and len(resistances) >= 3:
            break

    return sorted(supports[:3], reverse=True), sorted(resistances[:3])

# =============================
# 메시지 핸들러
# =============================
async def dot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text.strip().lower()

    # .sr btc
    if text.startswith(".sr"):
        parts = text.split()
        if len(parts) != 2:
            return

        coin = parts[1]
        candles = get_4h_candles(coin.upper() + "USDT")
        price, _, _ = get_coin_data(coin)

        if not candles or price is None:
            await context.bot.send_message(update.effective_chat.id, "❌ 데이터 오류")
            return

        sup, res = calc_sr(candles, price)

        msg = f"📊 {coin.upper()} 지지 / 저항\n\n🟢 지지\n"
        msg += "\n".join(f"- {format_price(s)}" for s in sup)
        msg += "\n\n🔴 저항\n"
        msg += "\n".join(f"- {format_price(r)}" for r in res)
        msg += f"\n\n💰 현재가 : {format_price(price)}"

        await context.bot.send_message(update.effective_chat.id, msg)
        return

    # .btc
    if not text.startswith("."):
        return

    coin = text[1:]
    price, percent, funding = get_coin_data(coin)
    if price is None:
        return

    arrow = "📈" if percent > 0 else "📉" if percent < 0 else "➖"
    sign = "+" if percent > 0 else ""

    msg = (
        f"🟦 {coin.upper()}USDT\n"
        f"현재가 : {format_price(price)}\n"
        f"전일대비 : {sign}{percent:.2f}% {arrow}\n"
        f"펀딩비 : {funding:.4f}%"
    )

    await context.bot.send_message(update.effective_chat.id, msg)

# =============================
# 실행
# =============================
if __name__ == "__main__":
    print("🚀 Bybit 시세 + SR 텔레그램 봇 시작")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dot_handler))
    app.run_polling(drop_pending_updates=True)

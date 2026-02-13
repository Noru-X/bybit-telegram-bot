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
# 봇 토큰
# =============================
TOKEN = "8219921205:AAEpH39t1DwA6VHeu8Atx-6DJNAEXsX_yp8"


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
# UTC 00:00 가격
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

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        candle = data["result"]["list"][0]
        return float(candle[1])
    except:
        return None


# =============================
# 현재 데이터
# =============================
def get_coin_data(coin):
    symbol = coin.upper() + "USDT"
    url = "https://api.bybit.com/v5/market/tickers"
    params = {"category": "linear", "symbol": symbol}

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        info = data["result"]["list"][0]

        price = float(info["lastPrice"])
        funding = float(info["fundingRate"]) * 100
        base = get_utc0_price(symbol)

        if base is None:
            return None, None, None

        percent = ((price - base) / base) * 100
        return price, percent, funding
    except:
        return None, None, None


# =============================
# 4H 캔들
# =============================
def get_4h_candles(symbol, limit=100):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": "240", "limit": limit}

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        return data["result"]["list"]
    except:
        return None


# =============================
# 지지저항 계산 (실전용)
# =============================
def calc_sr(candles, current):
    cluster = defaultdict(float)
    step = current * 0.005  # 0.5% 단위 (촘촘함 제거)

    for c in candles:
        high = float(c[2])
        low = float(c[3])
        vol = float(c[5])
        mid = (high + low) / 2
        key = round(mid / step) * step

        # 체류 + 거래량 + 반복 가중
        cluster[key] += vol * 1.5

    # 점수순 정렬 (가장 VOC 큰 순)
    levels = sorted(cluster.items(), key=lambda x: x[1], reverse=True)

    supports = []
    resistances = []

    for price, score in levels:
        if price < current:
            if all(abs(price - s) > step for s in supports):
                supports.append(price)
        else:
            if all(abs(price - r) > step for r in resistances):
                resistances.append(price)

        # 최대 3개만
        if len(supports) >= 3 and len(resistances) >= 3:
            break

    # VOC 큰 순 3개만 취함
    supports = supports[:3]
    resistances = resistances[:3]

    # 응답 순서: 지지는 가격 높은 순, 저항은 가격 낮은 순
    supports.sort(reverse=True)
    resistances.sort()

    return supports, resistances


# =============================
# 핸들러
# =============================
async def dot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text.strip().lower()

    # =============================
    # 지지저항
    # =============================
    if text.startswith(".sr"):
        parts = text.split()
        if len(parts) != 2:
            return

        coin = parts[1]
        symbol = coin.upper() + "USDT"
        candles = get_4h_candles(symbol)
        if not candles:
            return

        price, _, _ = get_coin_data(coin)
        if price is None:
            return

        sup, res = calc_sr(candles, price)

        msg = f"📊 {coin.upper()} 지지 / 저항 (4H·100봉)\n\n"
        msg += "🟢 지지구간\n"
        for s in sup:
            msg += f"- {format_price(s)}\n"

        msg += "\n🔴 저항구간\n"
        for r in res:
            msg += f"- {format_price(r)}\n"

        msg += f"\n💰 현재가 : {format_price(price)}"

        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
        return

    # =============================
    # 기존 가격봇 (변경 없음)
    # =============================
    if not text.startswith("."):
        return
    if len(text) <= 1:
        return

    coin = text[1:]
    price, percent, funding = get_coin_data(coin)
    if price is None:
        return

    price_text = format_price(price)
    arrow = "➖"
    sign = ""
    if percent > 0:
        arrow = "📈"
        sign = "+"
    elif percent < 0:
        arrow = "📉"

    percent_text = f"{sign}{percent:.2f}%"

    if funding > 0:
        funding_text = f"+{funding:.4f}% 🟢"
    elif funding < 0:
        funding_text = f"{funding:.4f}% 🔴"
    else:
        funding_text = "0.0000%"

    msg = (
        f"🟦 {coin.upper()}USDT 🟦\n"
        f"현재가 :  {price_text}\n"
        f"전일대비 :  {percent_text} {arrow}\n"
        f"펀딩비 :  {funding_text}"
    )

    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)


# =============================
# 실행
# =============================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dot_handler))
    print("📊 Bybit 시세 + SR 봇 실행중...")
    app.run_polling()

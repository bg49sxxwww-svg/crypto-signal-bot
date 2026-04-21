import requests
import time
import datetime

TOKEN = "8754365158:AAEWuxaCPNmnf_cU-LJZEU0r8215AdEB1fo"
CHAT_ID = "7599785098"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

entry_price = {}
last_signal = {s: None for s in SYMBOLS}

stats = {"win": 0, "loss": 0, "total": 0}
performance = {"profit_pct": 0}

# ===== Telegram =====
def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        print("發送失敗")

# ===== API =====
def get_klines(symbol, interval="5m"):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        data = requests.get(url, timeout=5).json()
        return [float(x[4]) for x in data]
    except:
        return []

# ===== 指標 =====
def ma(data, n):
    if len(data) < n:
        return None
    return sum(data[-n:]) / n

def rsi(data, period=14):
    if len(data) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i-1]
        gains.append(max(diff,0))
        losses.append(abs(min(diff,0)))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def ema(data, period):
    k = 2 / (period + 1)
    ema_val = data[0]
    result = []
    for p in data:
        ema_val = p * k + ema_val * (1 - k)
        result.append(ema_val)
    return result

def macd(data):
    ema12 = ema(data, 12)
    ema26 = ema(data, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal = ema(macd_line, 9)
    return macd_line, signal

def atr(data, period=14):
    if len(data) < period + 1:
        return 0
    trs = [abs(data[i] - data[i-1]) for i in range(1, len(data))]
    return sum(trs[-period:]) / period

# ===== 等待K棒 =====
def wait_for_close():
    last_min = -1
    while True:
        now = datetime.datetime.utcnow()
        if now.minute % 5 == 0 and now.second < 2 and now.minute != last_min:
            last_min = now.minute
            break
        time.sleep(1)

# ===== 主邏輯 =====
def main_logic():
    for symbol in SYMBOLS:

        closes_5m = get_klines(symbol, "5m")
        closes_15m = get_klines(symbol, "15m")

        if len(closes_5m) < 30 or len(closes_15m) < 30:
            continue

        price = closes_5m[-1]

        ma8 = ma(closes_5m, 8)
        ma21 = ma(closes_5m, 21)
        ma8_prev = ma(closes_5m[:-1], 8)
        ma21_prev = ma(closes_5m[:-1], 21)

        rsi_val = rsi(closes_5m)

        macd_line, signal_line = macd(closes_5m)
        macd_now = macd_line[-1]
        macd_prev = macd_line[-2]
        signal_now = signal_line[-1]
        signal_prev = signal_line[-2]

        volatility = atr(closes_5m)

        trend_up = ma(closes_15m, 8) > ma(closes_15m, 21)
        trend_down = ma(closes_15m, 8) < ma(closes_15m, 21)

        # 過濾盤整
        if volatility < 5:
            continue

        score = 0
        if ma8 > ma21: score += 1
        if macd_now > signal_now: score += 1
        if rsi_val and rsi_val > 60: score += 1
        if trend_up: score += 1

        level = "🔥強" if score >= 4 else "⚠️中"

        # ===== 做多 =====
        if (
            ma8_prev < ma21_prev and ma8 > ma21 and
            macd_prev < signal_prev and macd_now > signal_now and
            rsi_val and rsi_val > 50 and trend_up
        ):
            if last_signal[symbol] != "long":
                entry_price[symbol] = price
                send_msg(f"{level} {symbol} 做多\n進場價:{price}")
                last_signal[symbol] = "long"

        # ===== 做空 =====
        elif (
            ma8_prev > ma21_prev and ma8 < ma21 and
            macd_prev > signal_prev and macd_now < signal_now and
            rsi_val and rsi_val < 50 and trend_down
        ):
            if last_signal[symbol] != "short":
                entry_price[symbol] = price
                send_msg(f"{level} {symbol} 做空\n進場價:{price}")
                last_signal[symbol] = "short"

        # ===== 停利停損 + 統計 =====
        if symbol in entry_price:
            ep = entry_price[symbol]

            if last_signal[symbol] == "long":
                change = (price - ep) / ep * 100

                if change >= 3:
                    stats["win"] += 1
                    stats["total"] += 1
                    performance["profit_pct"] += change
                    send_msg(f"🎯 {symbol} 停利 {round(change,2)}%")
                    del entry_price[symbol]

                elif change <= -2:
                    stats["loss"] += 1
                    stats["total"] += 1
                    performance["profit_pct"] += change
                    send_msg(f"❌ {symbol} 停損 {round(change,2)}%")
                    del entry_price[symbol]

# ===== 主迴圈 =====
while True:
    try:
        wait_for_close()
        main_logic()
    except Exception as e:
        print("錯誤:", e)
        time.sleep(10)

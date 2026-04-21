import requests
import time
import datetime

TOKEN = "8754365158:AAEWuxaCPNmnf_cU-LJZEU0r8215AdEB1fo"
CHAT_ID = "7599785098"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

entry_price = {}
last_signal = {s: None for s in SYMBOLS}

# ===== Telegram =====
def send_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

# ===== 取得K線 =====
def get_klines(symbol, interval="5m"):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
    data = requests.get(url).json()
    return [float(x[4]) for x in data]

# ===== MA =====
def ma(data, n):
    return sum(data[-n:]) / n

# ===== RSI =====
def rsi(data, period=14):
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

# ===== 等待K棒收盤 =====
def wait_for_close():
    while True:
        now = datetime.datetime.utcnow()
        if now.minute % 5 == 0 and now.second < 3:
            break
        time.sleep(1)

# ===== 主邏輯 =====
def main_logic():
    for symbol in SYMBOLS:

        closes_5m = get_klines(symbol, "5m")
        closes_15m = get_klines(symbol, "15m")

        price = closes_5m[-1]

        ma8 = ma(closes_5m, 8)
        ma21 = ma(closes_5m, 21)

        ma8_prev = ma(closes_5m[:-1], 8)
        ma21_prev = ma(closes_5m[:-1], 21)

        rsi_val = rsi(closes_5m)

        # ===== 多時間框過濾（15m趨勢）=====
        trend_up = ma(closes_15m, 8) > ma(closes_15m, 21)
        trend_down = ma(closes_15m, 8) < ma(closes_15m, 21)

        # ===== 做多 =====
        if ma8_prev < ma21_prev and ma8 > ma21 and rsi_val > 50 and trend_up:
            if last_signal[symbol] != "long":
                entry_price[symbol] = price

                send_msg(
                    f"📊 {symbol}\n\n"
                    f"📈 MA交叉做多\n"
                    f"📉 RSI：{round(rsi_val,2)}\n\n"
                    f"💰 進場價：{price}"
                )

                last_signal[symbol] = "long"

        # ===== 做空 =====
        elif ma8_prev > ma21_prev and ma8 < ma21 and rsi_val < 50 and trend_down:
            if last_signal[symbol] != "short":
                entry_price[symbol] = price

                send_msg(
                    f"📊 {symbol}\n\n"
                    f"📉 MA交叉做空\n"
                    f"📉 RSI：{round(rsi_val,2)}\n\n"
                    f"💰 進場價：{price}"
                )

                last_signal[symbol] = "short"

        # ===== 停利停損 =====
        if symbol in entry_price:
            ep = entry_price[symbol]

            # 多單
            if last_signal[symbol] == "long":
                if price >= ep * 1.03:
                    send_msg(f"🎯 {symbol} 停利 +3%")
                    del entry_price[symbol]

                elif price <= ep * 0.98:
                    send_msg(f"❌ {symbol} 停損 -2%")
                    del entry_price[symbol]

            # 空單
            elif last_signal[symbol] == "short":
                if price <= ep * 0.97:
                    send_msg(f"🎯 {symbol} 空單停利 +3%")
                    del entry_price[symbol]

                elif price >= ep * 1.02:
                    send_msg(f"❌ {symbol} 空單停損 -2%")
                    del entry_price[symbol]

# ===== 主迴圈 =====
while True:
    try:
        wait_for_close()
        main_logic()
    except Exception as e:
        print(e)
        time.sleep(10)

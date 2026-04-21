import requests
import time

TOKEN = "你的TelegramToken"
CHAT_ID = "你的ChatID"

def send_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

def get_price(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=30"
    data = requests.get(url).json()
    closes = [float(candle[4]) for candle in data]
    return closes

def ma(data, n):
    return sum(data[-n:]) / n

last_signal = {"BTCUSDT": None, "ETHUSDT": None}

while True:
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        closes = get_price(symbol)
        ma7 = ma(closes, 7)
        ma25 = ma(closes, 25)

        if ma7 > ma25 and last_signal[symbol] != "long":
            send_msg(f"{symbol} 📈 做多訊號")
            last_signal[symbol] = "long"

        elif ma7 < ma25 and last_signal[symbol] != "short":
            send_msg(f"{symbol} 📉 做空訊號")
            last_signal[symbol] = "short"

    time.sleep(60)

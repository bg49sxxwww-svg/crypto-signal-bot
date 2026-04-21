import requests, time, datetime, os

TOKEN = os.getenv("8754365158:AAEWuxaCPNmnf_cU-LJZEU0r8215AdEB1fo")
CHAT_ID = os.getenv("7599785098")

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT"]

last_signal = {s: None for s in SYMBOLS}
entry_price = {}
loss_streak = 0
pause_until = 0

# ===== Telegram =====
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        print("TG error")

# ===== API =====
def klines(symbol, interval):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
    data = requests.get(url, timeout=5).json()
    return [float(x[4]) for x in data]

# ===== 指標 =====
def ma(data,n): return sum(data[-n:])/n

def ema(data,p):
    k=2/(p+1); e=data[0]; arr=[]
    for d in data:
        e=d*k+e*(1-k); arr.append(e)
    return arr

def macd(data):
    e12=ema(data,12); e26=ema(data,26)
    m=[a-b for a,b in zip(e12,e26)]
    s=ema(m,9)
    return m,s

def rsi(data,p=14):
    g,l=[],[]
    for i in range(1,len(data)):
        d=data[i]-data[i-1]
        g.append(max(d,0)); l.append(abs(min(d,0)))
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    if al==0: return 100
    rs=ag/al
    return 100-(100/(1+rs))

def atr(data,p=14):
    tr=[abs(data[i]-data[i-1]) for i in range(1,len(data))]
    return sum(tr[-p:])/p

def boll(data,n=20):
    m=sum(data[-n:])/n
    std=(sum([(x-m)**2 for x in data[-n:]])/n)**0.5
    return m+2*std, m-2*std

def adx_sim(data,p=14):
    changes=[abs(data[i]-data[i-1]) for i in range(1,len(data))]
    return sum(changes[-p:])/p

# ===== 主邏輯 =====
def run():
    global loss_streak, pause_until

    if time.time() < pause_until:
        return

    for s in SYMBOLS:

        c1 = klines(s,"1h")
        c4 = klines(s,"4h")

        if len(c1)<30 or len(c4)<30:
            continue

        price = c1[-1]

        ma8 = ma(c1,8); ma21 = ma(c1,21)
        ma8_p = ma(c1[:-1],8); ma21_p = ma(c1[:-1],21)

        r = rsi(c1)

        m,sg = macd(c1)
        m0,m1 = m[-1],m[-2]
        s0,s1 = sg[-1],sg[-2]

        vol = atr(c1)
        trend_up = ma(c4,8) > ma(c4,21)
        trend_dn = ma(c4,8) < ma(c4,21)

        upper, lower = boll(c1)
        adx = adx_sim(c1)

        # ===== 過濾 =====
        if vol/price < 0.003: continue
        if adx < price*0.002: continue

        # ===== 做多 =====
        if (
            ma8_p < ma21_p and ma8 > ma21 and
            m1 < s1 and m0 > s0 and
            r > 55 and trend_up and
            price < upper and
            c1[-1] > c1[-2] > c1[-3]
        ):
            if last_signal[s] != "long":
                entry_price[s] = price
                send(f"📈 {s} 做多\n進場:{price}\nSL:{round(price*0.98,2)}\nTP:{round(price*1.03,2)}")
                last_signal[s] = "long"

        # ===== 做空 =====
        elif (
            ma8_p > ma21_p and ma8 < ma21 and
            m1 > s1 and m0 < s0 and
            r < 45 and trend_dn and
            price > lower and
            c1[-1] < c1[-2] < c1[-3]
        ):
            if last_signal[s] != "short":
                entry_price[s] = price
                send(f"📉 {s} 做空\n進場:{price}\nSL:{round(price*1.02,2)}\nTP:{round(price*0.97,2)}")
                last_signal[s] = "short"

        # ===== 出場統計 =====
        if s in entry_price:
            ep = entry_price[s]

            if last_signal[s] == "long":
                change = (price - ep) / ep * 100
            else:
                change = (ep - price) / ep * 100

            if change >= 3 or change <= -2:

                if change > 0:
                    loss_streak = 0
                    send(f"🎯 {s} 停利 {round(change,2)}%")
                else:
                    loss_streak += 1
                    send(f"❌ {s} 停損 {round(change,2)}%")

                del entry_price[s]

                if loss_streak >= 2:
                    pause_until = time.time() + 6*3600
                    send("⚠️ 連續虧損，暫停6小時")

run()

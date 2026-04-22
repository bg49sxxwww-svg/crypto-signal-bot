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
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
        print("TG:", msg)
    except Exception as e:
        print("TG error:", e)

# ===== API =====
def klines(symbol, interval):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        res = requests.get(url, timeout=5).json()

        if not isinstance(res, list):
            return []

        return [float(x[4]) for x in res if len(x) > 4]
    except Exception as e:
        print("API error:", e)
        return []

# ===== 指標 =====
def ma(data,n): return sum(data[-n:])/n if len(data)>=n else None

def ema(data,p):
    if len(data) < p: return []
    k=2/(p+1); e=data[0]; arr=[]
    for d in data:
        e=d*k+e*(1-k); arr.append(e)
    return arr

def macd(data):
    e12=ema(data,12); e26=ema(data,26)
    if len(e12)==0 or len(e26)==0: return [],[]
    m=[a-b for a,b in zip(e12,e26)]
    s=ema(m,9)
    return m,s

def rsi(data,p=14):
    if len(data)<p+1: return None
    g,l=[],[]
    for i in range(1,len(data)):
        d=data[i]-data[i-1]
        g.append(max(d,0)); l.append(abs(min(d,0)))
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    if al==0: return 100
    rs=ag/al
    return 100-(100/(1+rs))

def atr(data,p=14):
    if len(data)<p+1: return 0
    tr=[abs(data[i]-data[i-1]) for i in range(1,len(data))]
    return sum(tr[-p:])/p

def boll(data,n=20):
    if len(data)<n: return None,None
    m=sum(data[-n:])/n
    std=(sum([(x-m)**2 for x in data[-n:]])/n)**0.5
    return m+2*std, m-2*std

def adx_sim(data,p=14):
    if len(data)<p+1: return 0
    changes=[abs(data[i]-data[i-1]) for i in range(1,len(data))]
    return sum(changes[-p:])/p

# ===== 主邏輯 =====
def run():
    global loss_streak, pause_until

    print("Running at:", datetime.datetime.utcnow())

    if time.time() < pause_until:
        print("Paused...")
        return

    for s in SYMBOLS:

        c1 = klines(s,"1h")
        c4 = klines(s,"4h")

        if len(c1)<30 or len(c4)<30:
            print(s, "data not enough")
            continue

        price = c1[-1]

        ma8 = ma(c1,8); ma21 = ma(c1,21)
        ma8_p = ma(c1[:-1],8); ma21_p = ma(c1[:-1],21)

        if not ma8 or not ma21: continue

        r = rsi(c1)

        m,sg = macd(c1)
        if len(m)<2 or len(sg)<2: continue

        m0,m1 = m[-1],m[-2]
        s0,s1 = sg[-1],sg[-2]

        vol = atr(c1)
        trend_up = ma(c4,8) > ma(c4,21)
        trend_dn = ma(c4,8) < ma(c4,21)

        upper, lower = boll(c1)
        adx = adx_sim(c1)

        if not upper: continue

        # ===== 過濾 =====
        if vol/price < 0.003: continue
        if adx < price*0.002: continue

        # ===== 做多 =====
        if (
            ma8_p < ma21_p and ma8 > ma21 and
            m1 < s1 and m0 > s0 and
            r and r > 55 and trend_up and
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
            r and r < 45 and trend_dn and
            price > lower and
            c1[-1] < c1[-2] < c1[-3]
        ):
            if last_signal[s] != "short":
                entry_price[s] = price
                send(f"📉 {s} 做空\n進場:{price}\nSL:{round(price*1.02,2)}\nTP:{round(price*0.97,2)}")
                last_signal[s] = "short"

# ===== 主迴圈（關鍵）=====
if __name__ == "__main__":
    while True:
        try:
            run()
            time.sleep(3600)  # 每1小時
        except Exception as e:
            send(f"❌ 系統錯誤: {str(e)}")
            time.sleep(60)

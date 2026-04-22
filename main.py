import requests, time, datetime, os

TOKEN = os.getenv("8754365158:AAEWuxaCPNmnf_cU-LJZEU0r8215AdEB1fo")
CHAT_ID = os.getenv("7599785098")

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT"]

last_signal = {s: None for s in SYMBOLS}
entry_price = {}
sl_tp = {}  # {symbol: {"sl":..., "tp":..., "be_moved":False}}

loss_streak = 0
pause_until = 0

last_signal_time = time.time()
stats = {"win":0, "loss":0, "total":0}
performance = {"profit_pct":0}
last_report_day = None

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
    except:
        return []

# ===== 指標 =====
def ma(data,n): return sum(data[-n:])/n if len(data)>=n else None

def ema(data,p):
    if len(data)<p: return []
    k=2/(p+1); e=data[0]; arr=[]
    for d in data:
        e=d*k+e*(1-k); arr.append(e)
    return arr

def macd(data):
    e12=ema(data,12); e26=ema(data,26)
    if not e12 or not e26: return [],[]
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
    global loss_streak, pause_until, last_signal_time, last_report_day

    print("Running:", datetime.datetime.utcnow())

    if time.time() < pause_until:
        print("Paused...")
        return

    status = []

    for s in SYMBOLS:

        c1 = klines(s,"1h")
        c4 = klines(s,"4h")

        if len(c1)<30 or len(c4)<30:
            status.append(f"{s} 資料不足")
            continue

        price = c1[-1]

        ma8 = ma(c1,8); ma21 = ma(c1,21)
        ma8_p = ma(c1[:-1],8); ma21_p = ma(c1[:-1],21)
        if not ma8 or not ma21:
            continue

        r = rsi(c1)

        m,sg = macd(c1)
        if len(m)<2 or len(sg)<2:
            continue

        m0,m1 = m[-1],m[-2]
        s0,s1 = sg[-1],sg[-2]

        vol = atr(c1)
        trend_up = ma(c4,8) > ma(c4,21)
        trend_dn = ma(c4,8) < ma(c4,21)

        upper, lower = boll(c1)
        adx = adx_sim(c1)
        if not upper:
            continue

        # ===== 過濾 =====
        if vol/price < 0.003:
            status.append(f"{s} 震盪")
            continue
        if adx < price*0.002:
            status.append(f"{s} 無趨勢")
            continue

        # ===== 進場 =====
        if (
            ma8_p < ma21_p and ma8 > ma21 and
            m1 < s1 and m0 > s0 and
            r and r > 55 and trend_up and
            price < upper and
            c1[-1] > c1[-2] > c1[-3]
        ):
            if last_signal[s] != "long":
                entry_price[s] = price
                atr_val = atr(c1)
                sl = price - atr_val*1.5
                tp = price + atr_val*2.5
                sl_tp[s] = {"sl":sl,"tp":tp,"be":False}
                send(f"📈 {s} 做多\n進場:{price}\nSL:{round(sl,2)}")
                last_signal[s] = "long"
                last_signal_time = time.time()
                status.append(f"{s} 做多")

        elif (
            ma8_p > ma21_p and ma8 < ma21 and
            m1 > s1 and m0 < s0 and
            r and r < 45 and trend_dn and
            price > lower and
            c1[-1] < c1[-2] < c1[-3]
        ):
            if last_signal[s] != "short":
                entry_price[s] = price
                atr_val = atr(c1)
                sl = price + atr_val*1.5
                tp = price - atr_val*2.5
                sl_tp[s] = {"sl":sl,"tp":tp,"be":False}
                send(f"📉 {s} 做空\n進場:{price}\nSL:{round(sl,2)}")
                last_signal[s] = "short"
                last_signal_time = time.time()
                status.append(f"{s} 做空")

        # ===== 出場 =====
        if s in entry_price:
            ep = entry_price[s]
            sl = sl_tp[s]["sl"]
            tp = sl_tp[s]["tp"]

            # 移動停利（保本）
            if not sl_tp[s]["be"]:
                if last_signal[s]=="long" and price >= ep*1.015:
                    sl_tp[s]["sl"] = ep
                    sl_tp[s]["be"] = True
                elif last_signal[s]=="short" and price <= ep*0.985:
                    sl_tp[s]["sl"] = ep
                    sl_tp[s]["be"] = True

            result = None

            if last_signal[s]=="long":
                if price <= sl_tp[s]["sl"]:
                    result="sl"
                elif price >= tp:
                    result="tp"
            else:
                if price >= sl_tp[s]["sl"]:
                    result="sl"
                elif price <= tp:
                    result="tp"

            if result:
                change = (price-ep)/ep*100 if last_signal[s]=="long" else (ep-price)/ep*100

                stats["total"] += 1
                performance["profit_pct"] += change

                if result=="tp":
                    stats["win"] += 1
                    loss_streak = 0
                    send(f"🎯 {s} 停利 {round(change,2)}%")
                else:
                    stats["loss"] += 1
                    loss_streak += 1
                    send(f"❌ {s} 停損 {round(change,2)}%")

                del entry_price[s]
                del sl_tp[s]

                if loss_streak >= 3:
                    pause_until = time.time() + 12*3600
                    send("⚠️ 連續虧損，暫停12小時")

        if s not in status:
            status.append(f"{s} 無訊號")

    # ===== 心跳 =====
    send("🟡 系統狀態\n" + "\n".join(status))

    # ===== 無訊號提醒 =====
    if time.time() - last_signal_time > 7200:
        send("⚠️ 超過2小時無訊號")

    # ===== 每日報告 =====
    today = datetime.datetime.utcnow().date()
    if last_report_day != today and stats["total"] > 0:
        winrate = stats["win"]/stats["total"]*100
        send(f"📊 每日報告\n勝率:{round(winrate,2)}%\n交易:{stats['total']}\n損益:{round(performance['profit_pct'],2)}%")
        last_report_day = today

# ===== 主迴圈 =====
if __name__ == "__main__":
    while True:
        try:
            run()
            time.sleep(300)  # 5分鐘檢查（避免漏停損）
        except Exception as e:
            send(f"❌ 系統錯誤: {str(e)}")
            time.sleep(60)

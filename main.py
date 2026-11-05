# ============================================================
# Crypto Signal Bot
# 六項加密貨幣分析與 Telegram 推播
# 執行方式：python main.py（單次執行，適用 GitHub Actions）
# ============================================================

import os
import sys
import time
import logging
import statistics
import datetime
import xml.etree.ElementTree as ET

import requests


# -------------------- 基本設定 --------------------

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

OKX_URL = "https://www.okx.com"
NEWS_RSS_URL = "https://www.coindesk.com/arc/outboundfeeds/rss/"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
]

REQUEST_TIMEOUT = 20
FEE_RATE = 0.001  # 回測單邊手續費假設 0.1%

SLIPPAGE_RATE = 0.0005
BACKTEST_DAYS = 90
BACKTEST_MIN_TRADES = 20
BACKTEST_MAX_BARS = BACKTEST_DAYS * 24 + 100

MAX_IDEAS = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# -------------------- Telegram --------------------

def send_telegram(message):
    """傳送 Telegram 訊息，並檢查 API 是否成功。"""

    if not TOKEN or not CHAT_ID:
        logging.error("缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            logging.error("Telegram API 回傳失敗：%s", result)
            return False

        return True

    except requests.RequestException as error:
        logging.error("Telegram 傳送失敗：%s", error)
        return False


def send_long_message(message):
    """避免單則 Telegram 訊息過長。"""

    max_length = 3800

    for start in range(0, len(message), max_length):
        if not send_telegram(message[start:start + max_length]):
            return False
        time.sleep(0.3)

    return True


# -------------------- 市場資料 --------------------

def get_klines(symbol, interval="1h", limit=500):
    """使用 OKX 公開 API 取得 OHLCV K 線資料。"""

    bar_map = {
        "1h": "1H",
        "1d": "1D",
        "1w": "1W",
    }

    bar = bar_map.get(interval.lower())

    if not bar:
        logging.error("不支援的週期：%s", interval)
        return []

    inst_id = symbol.replace("USDT", "-USDT")

    try:
        response = requests.get(
            f"{OKX_URL}/api/v5/market/candles",
            params={
                "instId": inst_id,
                "bar": bar,
                "limit": str(min(limit, 300)),
            },
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": "CryptoSignalBot/1.0"
            },
        )

        response.raise_for_status()
        payload = response.json()

        if payload.get("code") != "0":
            logging.warning(
                "%s API錯誤：%s",
                symbol,
                payload.get("msg")
            )
            return []

        raw = payload.get("data", [])
        candles = []

        # OKX 回傳由新到舊，反轉為舊到新
        for item in reversed(raw):

            if len(item) < 9:
                continue

            # 只使用已收盤 K 線
            if str(item[8]) != "1":
                continue

            candles.append({
                "time": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
            })

        if not candles:
            logging.warning(
                "%s %s 沒有有效 K 線",
                symbol,
                interval
            )

        return candles

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError
    ) as error:

        logging.warning(
            "%s %s OKX資料取得失敗：%s",
            symbol,
            interval,
            error
        )

        return []
        
def get_backtest_klines(symbol, days=BACKTEST_DAYS):
    """使用 OKX 歷史 K 線 API 取得回測資料。"""

    inst_id = symbol.replace("USDT", "-USDT")
    cutoff_ms = int(time.time() * 1000) - days * 24 * 60 * 60 * 1000

    candles_by_time = {}

    # 先取得最近 300 根已收盤 K 線
    recent = get_klines(symbol, "1h", 300)

    for candle in recent:
        if candle["time"] >= cutoff_ms:
            candles_by_time[candle["time"]] = candle

    if not candles_by_time:
        logging.warning("%s 沒有取得初始回測 K 線", symbol)
        return []

    oldest_ts = min(candles_by_time)

    # 使用 history-candles API 向更早的時間分頁
    while (
        oldest_ts > cutoff_ms
        and len(candles_by_time) < BACKTEST_MAX_BARS
    ):
        try:
            response = requests.get(
                f"{OKX_URL}/api/v5/market/history-candles",
                params={
                    "instId": inst_id,
                    "bar": "1H",
                    "after": str(oldest_ts),
                    "limit": "100",
                },
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": "CryptoSignalBot/1.0"
                },
            )

            response.raise_for_status()
            payload = response.json()

            if payload.get("code") != "0":
                logging.warning(
                    "%s 歷史 K 線 API 錯誤：%s",
                    symbol,
                    payload.get("msg")
                )
                break

            raw = payload.get("data", [])

            if not raw:
                break

            page_oldest_ts = min(int(item[0]) for item in raw)

            if page_oldest_ts >= oldest_ts:
                logging.warning(
                    "%s 歷史 K 線分頁沒有往前推進",
                    symbol
                )
                break

            # OKX 回傳由新到舊，轉為由舊到新
            for item in reversed(raw):
                if len(item) < 9:
                    continue

                if str(item[8]) != "1":
                    continue

                timestamp = int(item[0])

                if timestamp < cutoff_ms:
                    continue

                if timestamp >= oldest_ts:
                    continue

                candles_by_time[timestamp] = {
                    "time": timestamp,
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                }

            oldest_ts = page_oldest_ts

            time.sleep(0.12)

        except (
            requests.RequestException,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
        ) as error:
            logging.warning(
                "%s 歷史 K 線取得失敗：%s",
                symbol,
                error
            )
            break

    candles = sorted(
        candles_by_time.values(),
        key=lambda candle: candle["time"]
    )

    candles = candles[-BACKTEST_MAX_BARS:]

    actual_days = (
        (candles[-1]["time"] - candles[0]["time"])
        / (24 * 60 * 60 * 1000)
        if len(candles) >= 2
        else 0
    )

    logging.info(
        "%s 回測資料完成：%s 根 K 線，約 %.1f 天",
        symbol,
        len(candles),
        actual_days
    )

    return candles


# -------------------- 技術指標 --------------------

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values, period):
    if len(values) < period:
        return []

    multiplier = 2 / (period + 1)
    result = [values[0]]

    for value in values[1:]:
        result.append(
            value * multiplier + result[-1] * (1 - multiplier)
        )

    return result


def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(change, 0) for change in changes]
    losses = [abs(min(change, 0)) for change in changes]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )

        true_ranges.append(tr)

    return sum(true_ranges[-period:]) / period


def calculate_macd(values):
    fast = ema_series(values, 12)
    slow = ema_series(values, 26)

    if not fast or not slow:
        return None, None

    macd_values = [
        fast_value - slow_value
        for fast_value, slow_value in zip(fast, slow)
    ]

    signal_values = ema_series(macd_values, 9)

    if not signal_values:
        return None, None

    return macd_values[-1], signal_values[-1]


def calculate_support_resistance(candles, period=50):
    recent = candles[-period:]

    support = min(candle["low"] for candle in recent)
    resistance = max(candle["high"] for candle in recent)

    return support, resistance


# -------------------- 市場技術分析 --------------------

def analyze_market(symbol):
    hourly = get_klines(symbol, "1h", 300)
    daily = get_klines(symbol, "1d", 200)
    weekly = get_klines(symbol, "1w", 100)

    if min(len(hourly), len(daily), len(weekly)) < 30:
        return None

    prices = [candle["close"] for candle in hourly]
    daily_prices = [candle["close"] for candle in daily]
    weekly_prices = [candle["close"] for candle in weekly]

    price = prices[-1]

    ma8 = sma(prices, 8)
    ma21 = sma(prices, 21)
    ma55 = sma(prices, 55)

    daily_ma20 = sma(daily_prices, 20)
    weekly_ma20 = sma(weekly_prices, 20)

    rsi = calculate_rsi(prices)
    atr = calculate_atr(hourly)
    macd, signal = calculate_macd(prices)

    support, resistance = calculate_support_resistance(hourly)

    if None in (
        ma8, ma21, ma55, daily_ma20,
        weekly_ma20, rsi, atr, macd, signal
    ):
        return None

    hourly_trend = (
        "偏多" if ma8 > ma21 > ma55
        else "偏空" if ma8 < ma21 < ma55
        else "震盪"
    )

    daily_trend = "偏多" if price > daily_ma20 else "偏空"
    weekly_trend = (
        "偏多" if weekly_prices[-1] > weekly_ma20
        else "偏空"
    )

    if (
        hourly_trend == "偏多"
        and daily_trend == "偏多"
        and weekly_trend == "偏多"
        and rsi > 50
        and macd > signal
    ):
        decision = "買進觀察"

    elif (
        hourly_trend == "偏空"
        and daily_trend == "偏空"
        and weekly_trend == "偏空"
        and rsi < 50
        and macd < signal
    ):
        decision = "賣出／避開做多"

    else:
        decision = "觀望"

    return {
        "symbol": symbol,
        "price": price,
        "hourly_trend": hourly_trend,
        "daily_trend": daily_trend,
        "weekly_trend": weekly_trend,
        "rsi": rsi,
        "macd": macd,
        "signal": signal,
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "decision": decision,
        "candles": hourly,
    }


# -------------------- 交易點子產生器 --------------------

def generate_trade_ideas(analyses):
    ideas = []

    for data in analyses:
        if data is None:
            continue

        price = data["price"]
        atr = data["atr"]
        direction = None

        if (
            data["hourly_trend"] == "偏多"
            and data["daily_trend"] == "偏多"
            and data["weekly_trend"] == "偏多"
            and data["rsi"] >= 55
            and data["macd"] > data["signal"]
        ):
            direction = "LONG"

        elif (
            data["hourly_trend"] == "偏空"
            and data["daily_trend"] == "偏空"
            and data["weekly_trend"] == "偏空"
            and data["rsi"] <= 45
            and data["macd"] < data["signal"]
        ):
            direction = "SHORT"

        if direction is None or atr <= 0:
            continue

        if direction == "LONG":
            entry = price
            stop = price - atr * 1.5
            target = price + atr * 2.5
        else:
            entry = price
            stop = price + atr * 1.5
            target = price - atr * 2.5

        risk = abs(entry - stop)
        reward = abs(target - entry)

        if risk <= 0:
            continue

        rr = reward / risk

        if rr < 1.5:
            continue

        ideas.append({
            "symbol": data["symbol"],
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "target": target,
            "rr": rr,
            "rsi": data["rsi"],
        })

    ideas.sort(key=lambda item: item["rr"], reverse=True)

    return ideas[:MAX_IDEAS]


# -------------------- 策略回測 --------------------

def backtest_ema_cross(symbol):
    """EMA 8/21 回測：下一根 K 線開盤成交，計入手續費及滑價。"""

    candles = get_backtest_klines(symbol, BACKTEST_DAYS)

    if len(candles) < 100:
        return {
            "insufficient_data": True,
            "bars": len(candles),
            "period_days": 0,
        }

    prices = [c["close"] for c in candles]
    fast = ema_series(prices, 8)
    slow = ema_series(prices, 21)

    trades = []
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    position = None

    for i in range(22, len(candles) - 1):
        previous_fast = fast[i - 1]
        previous_slow = slow[i - 1]
        current_fast = fast[i]
        current_slow = slow[i]

        cross_up = (
            previous_fast <= previous_slow
            and current_fast > current_slow
        )
        cross_down = (
            previous_fast >= previous_slow
            and current_fast < current_slow
        )

        next_open = candles[i + 1]["open"]
        next_close = candles[i + 1]["close"]

        if position is None and cross_up:
            position = next_open * (
                1 + FEE_RATE + SLIPPAGE_RATE
            )

        elif position is not None and cross_down:
            exit_price = next_open * (
                1 - FEE_RATE - SLIPPAGE_RATE
            )
            trade_return = exit_price / position - 1
            trades.append(trade_return)
            equity *= (1 + trade_return)
            position = None

        marked_equity = equity

        if position is not None:
            estimated_exit = next_close * (
                1 - FEE_RATE - SLIPPAGE_RATE
            )
            marked_equity = equity * (
                estimated_exit / position
            )

        peak = max(peak, marked_equity)
        drawdown = (
            (peak - marked_equity) / peak
            if peak > 0 else 0
        )
        max_drawdown = max(max_drawdown, drawdown)

    open_position = position is not None

    if open_position:
        final_price = candles[-1]["close"] * (
            1 - FEE_RATE - SLIPPAGE_RATE
        )
        final_equity = equity * (final_price / position)
    else:
        final_equity = equity

    wins = [x for x in trades if x > 0]
    losses = [x for x in trades if x < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0 else None
    )

    period_days = (
        candles[-1]["time"] - candles[0]["time"]
    ) / (24 * 60 * 60 * 1000)

    return {
        "trades": len(trades),
        "win_rate": (
            len(wins) / len(trades) * 100
            if trades else 0
        ),
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown * 100,
        "total_return": (final_equity - 1) * 100,
        "bars": len(candles),
        "period_days": period_days,
        "open_position": open_position,
        "low_sample": len(trades) < BACKTEST_MIN_TRADES,
        "insufficient_data": False,
    }


# -------------------- 新聞分析 --------------------

def get_crypto_news():
    """讀取公開 RSS 新聞標題，不將標題當成已驗證的交易訊號。"""

    try:
        response = requests.get(
            NEWS_RSS_URL,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "CryptoSignalBot/1.0"},
        )

        response.raise_for_status()

        root = ET.fromstring(response.content)
        items = root.findall(".//item")

        news = []

        for item in items[:8]:
            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            pub_date = item.findtext("pubDate", default="").strip()

            if title:
                news.append({
                    "title": title,
                    "link": link,
                    "date": pub_date,
                })

        return news

    except (requests.RequestException, ET.ParseError, ValueError) as error:
        logging.warning("新聞取得失敗：%s", error)
        return []


# -------------------- 六項分析報告 --------------------

def build_report(analyses, ideas, backtests, news):
    now = datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    report = [
        "【Crypto Signal Bot 加密貨幣市場報告】",
        f"資料時間：{now}",
        "資料來源：OKX 公開市場 API、CoinDesk RSS",
        "分析範圍：BTC、ETH、主要山寨幣",
        "",
    ]

    # 1. 交易點子
    report.append("【1. 交易點子產生器】")

    if ideas:
        for idea in ideas:
            report.extend([
                f"{idea['symbol']}｜{idea['direction']}",
                f"參考進場：{idea['entry']:.6g}",
                f"停損：{idea['stop']:.6g}",
                f"目標：{idea['target']:.6g}",
                f"風險報酬比：1:{idea['rr']:.2f}",
                f"RSI：{idea['rsi']:.1f}",
                "依據：多週期趨勢、RSI、MACD 同向條件",
                "",
            ])
    else:
        report.append("目前沒有符合設定條件的交易機會，不勉強產生訊號。\n")

    # 2. 技術分析
    report.append("【2. 自動化技術分析】")

    for data in analyses:
        if data is None:
            continue

        report.extend([
            f"{data['symbol']}｜價格：{data['price']:.6g}",
            (
                f"1H：{data['hourly_trend']}｜"
                f"日線：{data['daily_trend']}｜"
                f"週線：{data['weekly_trend']}"
            ),
            f"RSI：{data['rsi']:.1f}",
            f"支撐參考：{data['support']:.6g}",
            f"壓力參考：{data['resistance']:.6g}",
            f"判斷：{data['decision']}",
            "",
        ])

    # 3. 新聞
    report.append("【3. 新聞轉交易策略】")

    if news:
        report.append(
            "以下為新聞標題整理；尚未完成事件影響及市場反應驗證："
        )

        for item in news:
            report.append(f"- {item['title']}")
            if item["link"]:
                report.append(item["link"])
    else:
        report.append("目前無法取得新聞資料，暫不提供新聞交易判斷。")

    report.extend([
        "",
        "新聞策略限制：未完成全文及市場反應分析前，不視為交易訊號。",
        "",
    ])

    # 4. 回測
    report.append("【4. 策略回測】")
    report.append("策略：1H EMA 8/21 交叉；僅統計已完成的平倉交易。")
    report.append("假設：單邊手續費 0.1%，不含滑價、資金費率及槓桿。")

    for symbol, result in backtests.items():
        if result is None:
            report.append(f"{symbol}：歷史資料不足，無法回測。")
            continue

        pf = (
            f"{result['profit_factor']:.2f}"
            if result["profit_factor"] is not None
            else "無法計算"
        )

        report.extend([
            f"{symbol}：",
            f"交易次數：{result['trades']}",
            f"勝率：{result['win_rate']:.2f}%",
            f"Profit Factor：{pf}",
            f"最大回撤：{result['max_drawdown']:.2f}%",
            f"累積報酬：{result['total_return']:.2f}%",
            "",
        ])

    report.append(
        "注意：此為簡化歷史測試，不代表未來績效；"
        "尚未納入完整風險模型及所有實際交易成本。"
    )
    report.append("")

    # 5. 投資組合風險
    report.append("【5. 投資組合風險管理】")
    report.append(
        "尚未連接交易所帳戶或持倉資料。"
        "目前無法計算集中度、相關性、實際曝險或下跌 20% 情境。"
    )
    report.append(
        "請勿將本報告視為已檢查個人持倉；"
        "後續需提供持倉幣種、數量、成本及合約方向。"
    )
    report.append("")

    # 6. 交易日誌
    report.append("【6. 交易日誌分析師】")
    report.append(
        "尚未連接交易紀錄，因此無法分析最近 20 筆交易、"
        "重複錯誤或個人決策偏誤。"
    )
    report.append(
        "後續需建立可持續保存的交易日誌，"
        "包含進出場時間、方向、價格、數量、手續費及結果。"
    )
    report.append("")

    report.extend([
        "【風險聲明】",
        "本報告為市場資料分析與策略研究，不保證獲利，",
        "不構成投資建議。交易前請自行確認價格、流動性及風險。",
    ])

    return "\n".join(report)


# -------------------- 主程式 --------------------

def main():
    if not TOKEN or not CHAT_ID:
        logging.error(
            "環境變數未設定：TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
        )
        return 1

    logging.info("開始執行加密貨幣分析")

    analyses = []

    for symbol in SYMBOLS:
        logging.info("分析 %s", symbol)

        data = analyze_market(symbol)
        analyses.append(data)

        time.sleep(0.2)

    valid_analyses = [
        data for data in analyses
        if data is not None
    ]

    if not valid_analyses:
        logging.error("所有幣種均無有效行情資料")
        send_telegram(
            "【Crypto Signal Bot】\n"
            "本次分析失敗：無法取得足夠市場資料。\n"
            "請檢查 Binance API 或網路連線。"
        )
        return 1

    logging.info("產生交易點子")
    ideas = generate_trade_ideas(valid_analyses)

    logging.info("執行策略回測")
    backtests = {}

    for symbol in SYMBOLS:
        backtests[symbol] = backtest_ema_cross(symbol)
        time.sleep(0.2)

    logging.info("取得新聞")
    news = get_crypto_news()

    report = build_report(
        valid_analyses,
        ideas,
        backtests,
        news,
    )

    logging.info("傳送 Telegram 報告")

    if not send_long_message(report):
        logging.error("報告傳送失敗")
        return 1

    logging.info("本次分析完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
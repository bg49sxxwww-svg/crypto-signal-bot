# ============================================================
# Crypto Signal Bot
# 六項加密貨幣分析與 Telegram 推播
# 執行方式：python main.py（單次執行，適用 GitHub Actions）
# ============================================================

import os
import sys
import csv
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
            and 35 <= data["rsi"] <= 45
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


# -------------------- 策略回測與逐筆日誌 --------------------

TRADE_LOG_FIELDS = ["strategy", "symbol", "side", "entry_time_utc", "entry_price", "exit_time_utc", "exit_price", "exit_reason", "return_pct", "fee_rate_one_way", "slippage_rate_one_way"]


def utc_time_from_ms(timestamp_ms):
    return datetime.datetime.fromtimestamp(timestamp_ms / 1000, tz=datetime.timezone.utc).isoformat()


def record_closed_trade(trade_log, strategy, symbol, position, exit_timestamp, exit_fill, exit_reason, trade_return):
    if trade_log is None:
        return
    trade_log.append({
        "strategy": strategy, "symbol": symbol, "side": position["side"],
        "entry_time_utc": utc_time_from_ms(position["entry_time"]),
        "entry_price": round(position["entry"], 10),
        "exit_time_utc": utc_time_from_ms(exit_timestamp),
        "exit_price": round(exit_fill, 10), "exit_reason": exit_reason,
        "return_pct": round(trade_return * 100, 6),
        "fee_rate_one_way": FEE_RATE, "slippage_rate_one_way": SLIPPAGE_RATE,
    })


def write_trade_log(trade_log, path="trade_log.csv"):
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=TRADE_LOG_FIELDS)
        writer.writeheader()
        writer.writerows(trade_log)
    logging.info("逐筆交易日誌已輸出：%s，共 %s 筆", path, len(trade_log))


def backtest_ema_cross_baseline(symbol, candles=None, trade_log=None):
    """EMA 8/21 多空基準回測；與 P1 使用相同方向、成本及強制平倉口徑。"""

    if candles is None:
        candles = get_backtest_klines(symbol, BACKTEST_DAYS)

    if len(candles) < 100:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": None,
            "max_drawdown": 0.0,
            "total_return": 0.0,
            "bars": len(candles),
            "period_days": 0.0,
            "open_position": False,
            "forced_exit_at_end": False,
            "low_sample": True,
            "insufficient_data": True,
        }

    prices = [c["close"] for c in candles]
    fast = ema_series(prices, 8)
    slow = ema_series(prices, 21)

    trades = []
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    position = None
    forced_exit_at_end = False
    cost = FEE_RATE + SLIPPAGE_RATE

    for i in range(22, len(candles) - 1):
        cross_up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
        cross_down = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]

        next_open = candles[i + 1]["open"]
        next_close = candles[i + 1]["close"]

        # 反向交叉於下一根 K 線開盤平倉。
        if position is not None:
            should_exit = (
                position["side"] == "LONG" and cross_down
            ) or (
                position["side"] == "SHORT" and cross_up
            )

            if should_exit:
                if position["side"] == "LONG":
                    exit_fill = next_open * (1 - cost)
                    trade_return = exit_fill / position["entry"] - 1
                else:
                    exit_fill = next_open * (1 + cost)
                    trade_return = position["entry"] / exit_fill - 1

                trades.append(trade_return)
                record_closed_trade(trade_log, "baseline", symbol, position, candles[i + 1]["time"], exit_fill, "REVERSE_CROSS", trade_return)
                equity *= max(0.0, 1 + trade_return)
                position = None

        # 基準策略可做多及做空；交叉方向決定下一根開盤進場。
        if position is None:
            if cross_up:
                position = {
                    "side": "LONG",
                    "entry": next_open * (1 + cost),
                    "entry_time": candles[i + 1]["time"],
                }
            elif cross_down:
                position = {
                    "side": "SHORT",
                    "entry": next_open * (1 - cost),
                    "entry_time": candles[i + 1]["time"],
                }

        # 使用實際進場後該根 K 線收盤價標記未實現損益。
        marked_equity = equity
        if position is not None:
            if position["side"] == "LONG":
                mark_exit = next_close * (1 - cost)
                marked_equity = equity * (mark_exit / position["entry"])
            else:
                mark_exit = next_close * (1 + cost)
                marked_equity = equity * (position["entry"] / mark_exit)

        peak = max(peak, marked_equity)
        drawdown = (peak - marked_equity) / peak if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)



    if position is not None:
        final_close = candles[-1]["close"]
        if position["side"] == "LONG":
            final_exit = final_close * (1 - cost)
            final_return = final_exit / position["entry"] - 1
        else:
            final_exit = final_close * (1 + cost)
            final_return = position["entry"] / final_exit - 1

        trades.append(final_return)
        record_closed_trade(trade_log, "baseline", symbol, position, candles[-1]["time"], final_exit, "FORCED_END", final_return)
        equity *= max(0.0, 1 + final_return)
        position = None
        forced_exit_at_end = True

    wins = [value for value in trades if value > 0]
    losses = [value for value in trades if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    peak = max(peak, equity)
    final_drawdown = (peak - equity) / peak if peak > 0 else 0.0
    max_drawdown = max(max_drawdown, final_drawdown)
    period_days = (
        candles[-1]["time"] - candles[0]["time"]
    ) / (24 * 60 * 60 * 1000)

    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown * 100,
        "total_return": (equity - 1) * 100,
        "bars": len(candles),
        "period_days": period_days,
        "open_position": False,
        "forced_exit_at_end": forced_exit_at_end,
        "low_sample": len(trades) < BACKTEST_MIN_TRADES,
        "insufficient_data": False,
    }

def build_4h_candles(hourly_candles):
    """由已收盤 1H K 線聚合完整 4H K 線，避免額外 API 分頁及未收盤資料。"""
    interval_ms = 4 * 60 * 60 * 1000
    grouped = {}

    for candle in hourly_candles:
        bucket = (candle["time"] // interval_ms) * interval_ms
        grouped.setdefault(bucket, []).append(candle)

    result = []
    for bucket, rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda item: item["time"])
        expected = [bucket + i * 60 * 60 * 1000 for i in range(4)]
        if [row["time"] for row in rows] != expected:
            continue

        result.append({
            "time": bucket,
            "open": rows[0]["open"],
            "high": max(row["high"] for row in rows),
            "low": min(row["low"] for row in rows),
            "close": rows[-1]["close"],
            "volume": sum(row["volume"] for row in rows),
        })

    return result


def backtest_ema_cross(symbol, candles=None, trade_log=None):
    """
    P1 優化策略：
    - 1H EMA 8/21 交叉作為觸發
    - 已完成 4H EMA 8/21 同向過濾
    - RSI(14) 動能確認
    - ATR(14) 動態停損 1.5 ATR、停利 2.5 ATR
    - 單筆只持有一個方向；同根 K 線同時觸及停損與停利時，保守判定停損先成交
    """
    if candles is None:
        candles = get_backtest_klines(symbol, BACKTEST_DAYS)

    empty_result = {
        "trades": 0,
        "win_rate": 0.0,
        "profit_factor": None,
        "max_drawdown": 0.0,
        "max_close_drawdown": 0.0,
        "max_intrabar_drawdown": 0.0,
        "total_return": 0.0,
        "bars": len(candles),
        "period_days": 0.0,
        "open_position": False,
        "forced_exit_at_end": False,
        "low_sample": True,
        "insufficient_data": True,
    }

    if len(candles) < 250:
        return empty_result

    closes = [c["close"] for c in candles]
    fast = ema_series(closes, 8)
    slow = ema_series(closes, 21)
    atr_values = [
        calculate_atr(candles[max(0, i - 14):i + 1], 14)
        for i in range(len(candles))
    ]
    rsi_values = [
        calculate_rsi(closes[max(0, i - 14):i + 1], 14)
        for i in range(len(candles))
    ]

    four_hour = build_4h_candles(candles)
    if len(four_hour) < 25:
        return empty_result

    htf_closes = [c["close"] for c in four_hour]
    htf_fast = ema_series(htf_closes, 8)
    htf_slow = ema_series(htf_closes, 21)
    htf_index = {c["time"]: i for i, c in enumerate(four_hour)}
    four_hours_ms = 4 * 60 * 60 * 1000
    hour_ms = 60 * 60 * 1000

    trades = []
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    position = None
    forced_exit_at_end = False
    cost = FEE_RATE + SLIPPAGE_RATE

    for i in range(60, len(candles)):
        candle = candles[i]
        position_at_bar_start = position
        open_price = candle["open"]
        high_price = candle["high"]
        low_price = candle["low"]
        close_price = candle["close"]

        # 先處理既有倉位。若同根 K 線同時觸及停損與停利，採停損優先。
        if position is not None:
            side = position["side"]
            stop_hit = (
                low_price <= position["stop"]
                if side == "LONG"
                else high_price >= position["stop"]
            )
            target_hit = (
                high_price >= position["target"]
                if side == "LONG"
                else low_price <= position["target"]
            )

            # 反向交叉必須在前一根已收盤 K 線形成，於本根開盤執行。
            # 多單：EMA 快線由上往下穿越慢線；空單：EMA 快線由下往上穿越慢線。
            reverse_cross = (
                fast[i - 2] >= slow[i - 2] and fast[i - 1] < slow[i - 1]
                if side == "LONG"
                else fast[i - 2] <= slow[i - 2] and fast[i - 1] > slow[i - 1]
            )

            exit_reference = None
            exit_reason = None

            # 已確認反向訊號時，先按本根開盤出場，不再使用本根後續高低點。
            if reverse_cross:
                exit_reference = open_price
                exit_reason = "REVERSE_CROSS"
            elif stop_hit:
                exit_reference = (
                    min(open_price, position["stop"])
                    if side == "LONG"
                    else max(open_price, position["stop"])
                )
                exit_reason = "STOP_LOSS"
            elif target_hit:
                exit_reference = position["target"]
                exit_reason = "TAKE_PROFIT"

            if exit_reference is not None:
                if side == "LONG":
                    exit_fill = exit_reference * (1 - cost)
                    trade_return = exit_fill / position["entry"] - 1
                else:
                    exit_fill = exit_reference * (1 + cost)
                    trade_return = position["entry"] / exit_fill - 1

                trades.append(trade_return)
                record_closed_trade(trade_log, "P1", symbol, position, candle["time"], exit_fill, exit_reason, trade_return)
                equity *= max(0.0, 1 + trade_return)
                position = None

        # 使用目前已收盤 1H K 線的訊號，在下一根 K 線開盤進場。
        if position is None and i < len(candles) - 1:
            previous_fast = fast[i - 1]
            previous_slow = slow[i - 1]
            current_fast = fast[i]
            current_slow = slow[i]

            cross_up = previous_fast <= previous_slow and current_fast > current_slow
            cross_down = previous_fast >= previous_slow and current_fast < current_slow

            # 只使用本根 1H 收盤時已經完整收盤的 4H K 線，避免未來資料。
            close_time = candle["time"] + hour_ms
            # 只有結束時間已到達的 4H 區間才可使用；不可讀取尚未收盤的當前 4H K 線。
            completed_bucket = ((close_time // four_hours_ms) - 1) * four_hours_ms
            completed_idx = htf_index.get(completed_bucket)

            if completed_idx is not None and completed_idx >= 21:
                trend_up = htf_fast[completed_idx] > htf_slow[completed_idx]
                trend_down = htf_fast[completed_idx] < htf_slow[completed_idx]
                rsi = rsi_values[i]
                atr = atr_values[i]

                if atr is not None and atr > 0 and rsi is not None:
                    next_open = candles[i + 1]["open"]

                    if cross_up and trend_up and rsi >= 50:
                        entry_fill = next_open * (1 + cost)
                        position = {
                            "side": "LONG",
                            "entry": entry_fill,
                            "entry_time": candles[i + 1]["time"],
                            "stop": next_open - atr * 1.5,
                            "target": next_open + atr * 2.5,
                        }
                    elif cross_down and trend_down and rsi <= 50:
                        entry_fill = next_open * (1 - cost)
                        position = {
                            "side": "SHORT",
                            "entry": entry_fill,
                            "entry_time": candles[i + 1]["time"],
                            "stop": next_open + atr * 1.5,
                            "target": next_open - atr * 2.5,
                        }

        # 收盤價基準回撤：保留既有 max_drawdown 欄位語意。
        marked_equity = equity
        # 新倉位在下一根 K 線開盤成交，不可用進場前一根收盤價標記。
        if position is not None and position is position_at_bar_start:
            if position["side"] == "LONG":
                estimated_exit = close_price * (1 - cost)
                marked_equity = equity * (estimated_exit / position["entry"])
            else:
                estimated_exit = close_price * (1 + cost)
                marked_equity = equity * (position["entry"] / estimated_exit)

        peak = max(peak, marked_equity)
        drawdown = (peak - marked_equity) / peak if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)

    if position is not None:
        final_close = candles[-1]["close"]
        if position["side"] == "LONG":
            final_exit = final_close * (1 - cost)
            final_return = final_exit / position["entry"] - 1
        else:
            final_exit = final_close * (1 + cost)
            final_return = position["entry"] / final_exit - 1

        trades.append(final_return)
        record_closed_trade(trade_log, "P1", symbol, position, candles[-1]["time"], final_exit, "FORCED_END", final_return)
        equity *= max(0.0, 1 + final_return)
        position = None
        forced_exit_at_end = True

    wins = [value for value in trades if value > 0]
    losses = [value for value in trades if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    peak = max(peak, equity)
    final_drawdown = (peak - equity) / peak if peak > 0 else 0.0
    max_drawdown = max(max_drawdown, final_drawdown)

    period_days = (candles[-1]["time"] - candles[0]["time"]) / (24 * hour_ms)

    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown * 100,
        "total_return": (equity - 1) * 100,
        "bars": len(candles),
        "period_days": period_days,
        "open_position": False,
        "forced_exit_at_end": forced_exit_at_end,
        "low_sample": len(trades) < BACKTEST_MIN_TRADES,
        "insufficient_data": False,
    }



def backtest_ema_triple(symbol, candles=None, trade_log=None):
    """
    C 組實驗策略：
    - 1H EMA 20/60 交叉作為觸發
    - 已完成 4H EMA 20/60/200 同向過濾
    - RSI(14) 動能確認
    - ATR(14) 動態停損 1.5 ATR、停利 2.5 ATR
    - 單筆只持有一個方向；同根 K 線同時觸及停損與停利時，保守判定停損先成交
    """
    if candles is None:
        candles = get_backtest_klines(symbol, BACKTEST_DAYS)

    empty_result = {
        "trades": 0,
        "win_rate": 0.0,
        "profit_factor": None,
        "max_drawdown": 0.0,
        "total_return": 0.0,
        "bars": len(candles),
        "period_days": 0.0,
        "open_position": False,
        "forced_exit_at_end": False,
        "low_sample": True,
        "insufficient_data": True,
    }

    if len(candles) < 250:
        return empty_result

    closes = [c["close"] for c in candles]
    fast = ema_series(closes, 20)
    slow = ema_series(closes, 60)
    atr_values = [
        calculate_atr(candles[max(0, i - 14):i + 1], 14)
        for i in range(len(candles))
    ]
    rsi_values = [
        calculate_rsi(closes[max(0, i - 14):i + 1], 14)
        for i in range(len(candles))
    ]

    four_hour = build_4h_candles(candles)
    if len(four_hour) < 205:
        return empty_result

    htf_closes = [c["close"] for c in four_hour]
    htf_fast = ema_series(htf_closes, 20)
    htf_slow = ema_series(htf_closes, 60)
    htf_long = ema_series(htf_closes, 200)
    htf_index = {c["time"]: i for i, c in enumerate(four_hour)}
    four_hours_ms = 4 * 60 * 60 * 1000
    hour_ms = 60 * 60 * 1000

    trades = []
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    position = None
    forced_exit_at_end = False
    cost = FEE_RATE + SLIPPAGE_RATE

    for i in range(60, len(candles)):
        candle = candles[i]
        position_at_bar_start = position
        open_price = candle["open"]
        high_price = candle["high"]
        low_price = candle["low"]
        close_price = candle["close"]

        # 先處理既有倉位。若同根 K 線同時觸及停損與停利，採停損優先。
        if position is not None:
            side = position["side"]
            stop_hit = (
                low_price <= position["stop"]
                if side == "LONG"
                else high_price >= position["stop"]
            )
            target_hit = (
                high_price >= position["target"]
                if side == "LONG"
                else low_price <= position["target"]
            )

            # 反向交叉必須在前一根已收盤 K 線形成，於本根開盤執行。
            # 多單：EMA 快線由上往下穿越慢線；空單：EMA 快線由下往上穿越慢線。
            reverse_cross = (
                fast[i - 2] >= slow[i - 2] and fast[i - 1] < slow[i - 1]
                if side == "LONG"
                else fast[i - 2] <= slow[i - 2] and fast[i - 1] > slow[i - 1]
            )

            exit_reference = None
            exit_reason = None

            # 已確認反向訊號時，先按本根開盤出場，不再使用本根後續高低點。
            if reverse_cross:
                exit_reference = open_price
                exit_reason = "REVERSE_CROSS"
            elif stop_hit:
                exit_reference = (
                    min(open_price, position["stop"])
                    if side == "LONG"
                    else max(open_price, position["stop"])
                )
                exit_reason = "STOP_LOSS"
            elif target_hit:
                exit_reference = position["target"]
                exit_reason = "TAKE_PROFIT"

            if exit_reference is not None:
                if side == "LONG":
                    exit_fill = exit_reference * (1 - cost)
                    trade_return = exit_fill / position["entry"] - 1
                else:
                    exit_fill = exit_reference * (1 + cost)
                    trade_return = position["entry"] / exit_fill - 1

                trades.append(trade_return)
                record_closed_trade(trade_log, "C", symbol, position, candle["time"], exit_fill, exit_reason, trade_return)
                equity *= max(0.0, 1 + trade_return)
                position = None

        # 使用目前已收盤 1H K 線的訊號，在下一根 K 線開盤進場。
        if position is None and i < len(candles) - 1:
            previous_fast = fast[i - 1]
            previous_slow = slow[i - 1]
            current_fast = fast[i]
            current_slow = slow[i]

            cross_up = previous_fast <= previous_slow and current_fast > current_slow
            cross_down = previous_fast >= previous_slow and current_fast < current_slow

            # 只使用本根 1H 收盤時已經完整收盤的 4H K 線，避免未來資料。
            close_time = candle["time"] + hour_ms
            # 只有結束時間已到達的 4H 區間才可使用；不可讀取尚未收盤的當前 4H K 線。
            completed_bucket = ((close_time // four_hours_ms) - 1) * four_hours_ms
            completed_idx = htf_index.get(completed_bucket)

            if completed_idx is not None and completed_idx >= 199:
                trend_up = (
                    htf_fast[completed_idx] > htf_slow[completed_idx]
                    and htf_closes[completed_idx] > htf_long[completed_idx]
                )
                trend_down = (
                    htf_fast[completed_idx] < htf_slow[completed_idx]
                    and htf_closes[completed_idx] < htf_long[completed_idx]
                )
                rsi = rsi_values[i]
                atr = atr_values[i]

                if atr is not None and atr > 0 and rsi is not None:
                    next_open = candles[i + 1]["open"]

                    if cross_up and trend_up and rsi >= 50:
                        entry_fill = next_open * (1 + cost)
                        position = {
                            "side": "LONG",
                            "entry": entry_fill,
                            "entry_time": candles[i + 1]["time"],
                            "stop": next_open - atr * 1.5,
                            "target": next_open + atr * 2.5,
                        }
                    elif cross_down and trend_down and rsi <= 50:
                        entry_fill = next_open * (1 - cost)
                        position = {
                            "side": "SHORT",
                            "entry": entry_fill,
                            "entry_time": candles[i + 1]["time"],
                            "stop": next_open + atr * 1.5,
                            "target": next_open - atr * 2.5,
                        }

        # 以收盤價估算未實現權益，納入最大回撤監控。
        marked_equity = equity
        # 新倉位在下一根 K 線開盤成交，不可用進場前一根收盤價標記。
        if position is not None and position is position_at_bar_start:
            if position["side"] == "LONG":
                estimated_exit = close_price * (1 - cost)
                marked_equity = equity * (estimated_exit / position["entry"])
            else:
                estimated_exit = close_price * (1 + cost)
                marked_equity = equity * (position["entry"] / estimated_exit)

        peak = max(peak, marked_equity)
        drawdown = (peak - marked_equity) / peak if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)

    if position is not None:
        final_close = candles[-1]["close"]
        if position["side"] == "LONG":
            final_exit = final_close * (1 - cost)
            final_return = final_exit / position["entry"] - 1
        else:
            final_exit = final_close * (1 + cost)
            final_return = position["entry"] / final_exit - 1

        trades.append(final_return)
        record_closed_trade(trade_log, "D", symbol, position, candles[-1]["time"], final_exit, "FORCED_END", final_return)
        equity *= max(0.0, 1 + final_return)
        position = None
        forced_exit_at_end = True

    wins = [value for value in trades if value > 0]
    losses = [value for value in trades if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    peak = max(peak, equity)
    final_drawdown = (peak - equity) / peak if peak > 0 else 0.0
    max_drawdown = max(max_drawdown, final_drawdown)

    period_days = (candles[-1]["time"] - candles[0]["time"]) / (24 * hour_ms)

    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown * 100,
        "total_return": (equity - 1) * 100,
        "bars": len(candles),
        "period_days": period_days,
        "open_position": False,
        "forced_exit_at_end": forced_exit_at_end,
        "low_sample": len(trades) < BACKTEST_MIN_TRADES,
        "insufficient_data": False,
    }



def d_rsi_filter(direction, rsi):
    """D 組避免在 RSI 極端區追價；區間端點包含在內。"""
    if rsi is None:
        return False
    if direction == "LONG":
        return 55 <= rsi <= 68
    if direction == "SHORT":
        return 32 <= rsi <= 45
    return False


def backtest_ema_filtered(symbol, candles=None, trade_log=None):
    """
    D 組 RSI 過濾策略：
    - 1H EMA 20/60 交叉作為觸發
    - 已完成 4H EMA 20/60/200 同向過濾
    - RSI(14) 動能確認
    - ATR(14) 動態停損 1.5 ATR、停利 2.5 ATR
    - 單筆只持有一個方向；同根 K 線同時觸及停損與停利時，保守判定停損先成交
    """
    if candles is None:
        candles = get_backtest_klines(symbol, BACKTEST_DAYS)

    empty_result = {
        "trades": 0,
        "win_rate": 0.0,
        "profit_factor": None,
        "max_drawdown": 0.0,
        "max_close_drawdown": 0.0,
        "max_intrabar_drawdown": 0.0,
        "total_return": 0.0,
        "bars": len(candles),
        "period_days": 0.0,
        "open_position": False,
        "forced_exit_at_end": False,
        "low_sample": True,
        "insufficient_data": True,
    }

    if len(candles) < 250:
        return empty_result

    closes = [c["close"] for c in candles]
    fast = ema_series(closes, 20)
    slow = ema_series(closes, 60)
    atr_values = [
        calculate_atr(candles[max(0, i - 14):i + 1], 14)
        for i in range(len(candles))
    ]
    rsi_values = [
        calculate_rsi(closes[max(0, i - 14):i + 1], 14)
        for i in range(len(candles))
    ]

    four_hour = build_4h_candles(candles)
    if len(four_hour) < 205:
        return empty_result

    htf_closes = [c["close"] for c in four_hour]
    htf_fast = ema_series(htf_closes, 20)
    htf_slow = ema_series(htf_closes, 60)
    htf_long = ema_series(htf_closes, 200)
    htf_index = {c["time"]: i for i, c in enumerate(four_hour)}
    four_hours_ms = 4 * 60 * 60 * 1000
    hour_ms = 60 * 60 * 1000

    trades = []
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    intrabar_peak = 1.0
    max_intrabar_drawdown = 0.0
    position = None
    forced_exit_at_end = False
    cost = FEE_RATE + SLIPPAGE_RATE

    for i in range(60, len(candles)):
        candle = candles[i]
        position_at_bar_start = position
        equity_at_bar_start = equity
        open_price = candle["open"]
        high_price = candle["high"]
        low_price = candle["low"]
        close_price = candle["close"]

        # 先處理既有倉位。若同根 K 線同時觸及停損與停利，採停損優先。
        if position is not None:
            side = position["side"]
            stop_hit = (
                low_price <= position["stop"]
                if side == "LONG"
                else high_price >= position["stop"]
            )
            target_hit = (
                high_price >= position["target"]
                if side == "LONG"
                else low_price <= position["target"]
            )

            # 反向交叉必須在前一根已收盤 K 線形成，於本根開盤執行。
            # 多單：EMA 快線由上往下穿越慢線；空單：EMA 快線由下往上穿越慢線。
            reverse_cross = (
                fast[i - 2] >= slow[i - 2] and fast[i - 1] < slow[i - 1]
                if side == "LONG"
                else fast[i - 2] <= slow[i - 2] and fast[i - 1] > slow[i - 1]
            )

            exit_reference = None
            exit_reason = None

            # 已確認反向訊號時，先按本根開盤出場，不再使用本根後續高低點。
            if reverse_cross:
                exit_reference = open_price
                exit_reason = "REVERSE_CROSS"
            elif stop_hit:
                exit_reference = (
                    min(open_price, position["stop"])
                    if side == "LONG"
                    else max(open_price, position["stop"])
                )
                exit_reason = "STOP_LOSS"
            elif target_hit:
                exit_reference = position["target"]
                exit_reason = "TAKE_PROFIT"

            if exit_reference is not None:
                if side == "LONG":
                    exit_fill = exit_reference * (1 - cost)
                    trade_return = exit_fill / position["entry"] - 1
                else:
                    exit_fill = exit_reference * (1 + cost)
                    trade_return = position["entry"] / exit_fill - 1

                trades.append(trade_return)
                record_closed_trade(trade_log, "D", symbol, position, candle["time"], exit_fill, exit_reason, trade_return)
                equity *= max(0.0, 1 + trade_return)
                position = None

        # 使用目前已收盤 1H K 線的訊號，在下一根 K 線開盤進場。
        if position is None and i < len(candles) - 1:
            previous_fast = fast[i - 1]
            previous_slow = slow[i - 1]
            current_fast = fast[i]
            current_slow = slow[i]

            cross_up = previous_fast <= previous_slow and current_fast > current_slow
            cross_down = previous_fast >= previous_slow and current_fast < current_slow

            # 只使用本根 1H 收盤時已經完整收盤的 4H K 線，避免未來資料。
            close_time = candle["time"] + hour_ms
            # 只有結束時間已到達的 4H 區間才可使用；不可讀取尚未收盤的當前 4H K 線。
            completed_bucket = ((close_time // four_hours_ms) - 1) * four_hours_ms
            completed_idx = htf_index.get(completed_bucket)

            if completed_idx is not None and completed_idx >= 199:
                trend_up = (
                    htf_fast[completed_idx] > htf_slow[completed_idx]
                    and htf_closes[completed_idx] > htf_long[completed_idx]
                )
                trend_down = (
                    htf_fast[completed_idx] < htf_slow[completed_idx]
                    and htf_closes[completed_idx] < htf_long[completed_idx]
                )
                rsi = rsi_values[i]
                atr = atr_values[i]

                if atr is not None and atr > 0 and rsi is not None:
                    next_open = candles[i + 1]["open"]

                    if cross_up and trend_up and d_rsi_filter("LONG", rsi):
                        entry_fill = next_open * (1 + cost)
                        position = {
                            "side": "LONG",
                            "entry": entry_fill,
                            "entry_time": candles[i + 1]["time"],
                            "stop": next_open - atr * 1.5,
                            "target": next_open + atr * 2.5,
                        }
                    elif cross_down and trend_down and d_rsi_filter("SHORT", rsi):
                        entry_fill = next_open * (1 - cost)
                        position = {
                            "side": "SHORT",
                            "entry": entry_fill,
                            "entry_time": candles[i + 1]["time"],
                            "stop": next_open + atr * 1.5,
                            "target": next_open - atr * 2.5,
                        }

        # 收盤價基準回撤：保留既有 max_drawdown 欄位語意。
        marked_equity = equity
        # 新倉位在下一根 K 線開盤成交，不可用進場前一根收盤價標記。
        if position is not None and position is position_at_bar_start:
            if position["side"] == "LONG":
                estimated_exit = close_price * (1 - cost)
                marked_equity = equity * (estimated_exit / position["entry"])
            else:
                estimated_exit = close_price * (1 + cost)
                marked_equity = equity * (position["entry"] / estimated_exit)

        peak = max(peak, marked_equity)
        drawdown = (peak - marked_equity) / peak if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)

        # 盤中保守估值：假設有利極值先於不利極值，避免低估同根 K 線內的回撤。
        intrabar_marked_equity = equity
        if position_at_bar_start is not None:
            side = position_at_bar_start["side"]
            target_only_exit = target_hit and not stop_hit and not reverse_cross
            if reverse_cross:
                favorable_reference = open_price
                adverse_reference = open_price
            elif side == "LONG":
                # 若本根只觸及停利，保守假設低點先於停利價；到達停利後不再計入後續波動。
                favorable_reference = position_at_bar_start["target"]
                adverse_reference = low_price
                if stop_hit:
                    favorable_reference = high_price
                    adverse_reference = min(
                        open_price, position_at_bar_start["stop"]
                    )
            else:
                # 空單方向相反：只觸及停利時，保守假設高點先於停利價。
                favorable_reference = position_at_bar_start["target"]
                adverse_reference = high_price
                if stop_hit:
                    favorable_reference = low_price
                    adverse_reference = max(
                        open_price, position_at_bar_start["stop"]
                    )

            if side == "LONG":
                favorable_exit = favorable_reference * (1 - cost)
                adverse_exit = adverse_reference * (1 - cost)
                favorable_equity = equity_at_bar_start * (
                    favorable_exit / position_at_bar_start["entry"]
                )
                intrabar_marked_equity = equity_at_bar_start * (
                    adverse_exit / position_at_bar_start["entry"]
                )
            else:
                favorable_exit = favorable_reference * (1 + cost)
                adverse_exit = adverse_reference * (1 + cost)
                favorable_equity = equity_at_bar_start * (
                    position_at_bar_start["entry"] / favorable_exit
                )
                intrabar_marked_equity = equity_at_bar_start * (
                    position_at_bar_start["entry"] / adverse_exit
                )
            # 單獨觸及停利時，先記錄不利極值，再記錄停利出場後的已實現權益；
            # 不把停利出場後的同根 K 線價格變動算進持倉回撤。
            if not target_only_exit:
                intrabar_peak = max(intrabar_peak, favorable_equity)

        intrabar_peak = max(intrabar_peak, intrabar_marked_equity)
        intrabar_drawdown = (
            (intrabar_peak - intrabar_marked_equity) / intrabar_peak
            if intrabar_peak > 0 else 0.0
        )
        max_intrabar_drawdown = max(
            max_intrabar_drawdown, intrabar_drawdown
        )
        # 本根 K 線的已實現權益只可成為下一根 K 線的峰值，避免時間順序倒置。
        intrabar_peak = max(intrabar_peak, equity)

    if position is not None:
        final_close = candles[-1]["close"]
        if position["side"] == "LONG":
            final_exit = final_close * (1 - cost)
            final_return = final_exit / position["entry"] - 1
        else:
            final_exit = final_close * (1 + cost)
            final_return = position["entry"] / final_exit - 1

        trades.append(final_return)
        record_closed_trade(trade_log, "D", symbol, position, candles[-1]["time"], final_exit, "FORCED_END", final_return)
        equity *= max(0.0, 1 + final_return)
        position = None
        forced_exit_at_end = True

    wins = [value for value in trades if value > 0]
    losses = [value for value in trades if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    peak = max(peak, equity)
    final_drawdown = (peak - equity) / peak if peak > 0 else 0.0
    max_drawdown = max(max_drawdown, final_drawdown)

    period_days = (candles[-1]["time"] - candles[0]["time"]) / (24 * hour_ms)

    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown * 100,
        "max_close_drawdown": max_drawdown * 100,
        "max_intrabar_drawdown": max_intrabar_drawdown * 100,
        "total_return": (equity - 1) * 100,
        "bars": len(candles),
        "period_days": period_days,
        "open_position": False,
        "forced_exit_at_end": forced_exit_at_end,
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


def summarize_recent_trades(trade_log, strategy="P1", limit=20):
    """只分析指定策略的已平倉回測紀錄，按出場時間取最近 N 筆。"""
    rows = [
        row for row in (trade_log or [])
        if str(row.get("strategy", "")).upper() == strategy.upper()
    ]
    rows.sort(key=lambda row: row.get("exit_time_utc", ""))

    recent = rows[-limit:]
    returns = []
    for row in recent:
        try:
            returns.append(float(row.get("return_pct", 0.0)))
        except (TypeError, ValueError):
            continue

    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    reasons = {}
    for row in recent:
        reason = row.get("exit_reason", "UNKNOWN") or "UNKNOWN"
        reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "available": bool(recent),
        "total_records": len(rows),
        "sample_size": len(returns),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(returns) * 100 if returns else 0.0,
        "profit_factor": profit_factor,
        "average_return": sum(returns) / len(returns) if returns else 0.0,
        "reasons": reasons,
        "first_exit_time": recent[0].get("exit_time_utc", "") if recent else "",
        "last_exit_time": recent[-1].get("exit_time_utc", "") if recent else "",
    }


# -------------------- 六項分析報告 --------------------

def build_report(analyses, ideas, backtests, news, trade_log=None):
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
            direction_label = (
                "做多 LONG（BUY）"
                if idea["direction"] == "LONG"
                else "做空 SHORT（SELL）"
            )
            report.extend([
                f"【{idea['symbol']}｜{direction_label}】",
                "訊號狀態：等待進場條件確認（不是已成交通知）",
                f"進場參考價：{idea['entry']:.6g}",
                f"停損 SL：{idea['stop']:.6g}",
                f"止盈 TP1：{idea['target']:.6g}",
                "止盈 TP2–TP4：尚未設定（目前策略只有單一 ATR 目標）",
                f"風險報酬比：1:{idea['rr']:.2f}",
                f"RSI：{idea['rsi']:.1f}",
                (
                    "訊號依據：多週期趨勢、RSI、MACD 同向條件；"
                    "SHORT RSI 限定 35–45，避免極度超賣追空"
                    if idea["direction"] == "SHORT"
                    else "訊號依據：多週期趨勢、RSI、MACD 同向條件"
                ),
                "執行提醒：價格偏離進場參考價或訊號失效時，不追價。",
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
    report.append("A 組基準：1H EMA 8/21 交叉，無 ATR 固定停損／停利；B 組 P1：1H EMA 8/21 + 已完成 4H EMA 8/21 趨勢 + RSI(14) + ATR 停損／停利；C 組：1H EMA 20/60 + 已完成 4H EMA 20/60/200 + RSI(14) + ATR 停損／停利；D 組：沿用 C 組架構，另限制做多 RSI 55–68、做空 RSI 32–45。")
    report.append("B／C／D 組使用 ATR(14) 停損 1.5 倍／停利 2.5 倍；A 組僅以反向 EMA 交叉出場。C／D 組的 EMA200 為 4H EMA200，不是日線 EMA200。")
    report.append("四組策略均於回測結束時強制平倉；B／C／D 同根 K 線同時觸及停損與停利時，保守採停損先成交。")
    report.append("假設：單邊手續費 0.1%、滑價 0.05%；不含資金費率及槓桿。")

    for symbol, pair in backtests.items():
        if pair is None:
            report.append(f"{symbol}：回測執行失敗，請檢查日誌。")
            continue

        for label, result in pair.items():
            report.append(f"{symbol}｜{ {'baseline': '基準策略', 'optimized': 'P1 優化策略', 'triple': 'C 組 EMA20/60/200 實驗'}.get(label, label) }")

            if result.get("insufficient_data", False):
                report.append(
                    f"資料不足（{result.get('bars', 0)} 根 K 線），未計算績效指標。"
                )
                report.append("")
                continue

            pf = (
                f"{result['profit_factor']:.2f}"
                if result["profit_factor"] is not None
                else "無法計算"
            )

            report.extend([
                f"交易次數：{result['trades']}",
                f"勝率：{result['win_rate']:.2f}%",
                f"Profit Factor：{pf}",
                f"收盤價基準最大回撤：{result['max_drawdown']:.2f}%",
                *(
                    [f"盤中估算最大回撤：{result['max_intrabar_drawdown']:.2f}%"]
                    if "max_intrabar_drawdown" in result else []
                ),
                f"累積報酬：{result['total_return']:.2f}%",
                (
                    "低樣本警示：交易次數少於設定門檻"
                    if result.get("low_sample", False)
                    else "樣本數：達到最低交易次數門檻"
                ),
                (
                    "期末未平倉部位：已按最後收盤價強制平倉"
                    if result.get("forced_exit_at_end", False)
                    else "期末未平倉部位：無"
                ),
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

    # 6. 交易日誌：本次回測紀錄，不代表交易所實際成交
    report.append("【6. 交易日誌分析師】")
    summary = summarize_recent_trades(trade_log, strategy="P1", limit=20)

    if summary["available"]:
        pf = (
            f"{summary['profit_factor']:.2f}"
            if summary["profit_factor"] is not None
            else "無法計算"
        )
        report.extend([
            "資料類型：P1 歷史回測已平倉紀錄，非個人實盤成交。",
            f"P1 累計紀錄：{summary['total_records']} 筆",
            f"最近樣本：{summary['sample_size']} 筆",
            f"區間：{summary['first_exit_time']} 至 {summary['last_exit_time']}",
            f"勝率：{summary['win_rate']:.2f}%",
            f"Profit Factor：{pf}",
            f"平均單筆報酬：{summary['average_return']:.3f}%",
            f"獲利／虧損筆數：{summary['wins']}／{summary['losses']}",
            "最近樣本出場原因：" + "、".join(
                f"{reason} {count}筆"
                for reason, count in sorted(summary["reasons"].items())
            ),
            "限制：此摘要只反映策略回測，不代表使用者個人交易行為。",
        ])
    else:
        report.append("本次沒有可讀取的 P1 已平倉交易紀錄，無法分析最近 20 筆。")
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
    trade_log = []

    for symbol in SYMBOLS:
        try:
            historical_candles = get_backtest_klines(symbol, BACKTEST_DAYS)
            backtests[symbol] = {
                "baseline": backtest_ema_cross_baseline(symbol, historical_candles, trade_log),
                "optimized": backtest_ema_cross(symbol, historical_candles, trade_log),
                "triple": backtest_ema_triple(symbol, historical_candles, trade_log),
                "filtered": backtest_ema_filtered(symbol, historical_candles, trade_log),
            }
        except Exception:
            logging.exception("%s 回測執行失敗", symbol)
            backtests[symbol] = None
        time.sleep(0.2)

    try:
        write_trade_log(trade_log)
    except OSError:
        logging.exception("逐筆交易日誌輸出失敗")

    logging.info("取得新聞")
    news = get_crypto_news()

    report = build_report(
        valid_analyses,
        ideas,
        backtests,
        news,
        trade_log=trade_log,
    )

    logging.info("傳送 Telegram 報告")

    if not send_long_message(report):
        logging.error("報告傳送失敗")
        return 1

    logging.info("本次分析完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
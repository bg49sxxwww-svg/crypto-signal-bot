"""Live read-only smoke check for the public OKX history endpoint."""
import json
import time

from experiments.d_entry_quality.data_loader import HOUR_MS, fetch_okx_1h_history

end_ms = (int(time.time() * 1000) // HOUR_MS) * HOUR_MS
start_ms = end_ms - 48 * HOUR_MS
candles, report = fetch_okx_1h_history("BTCUSDT", start_ms, end_ms)
print(json.dumps(report, ensure_ascii=False, indent=2))
if not report["complete"] or len(candles) != 48:
    raise SystemExit("OKX live 48-hour smoke check failed")

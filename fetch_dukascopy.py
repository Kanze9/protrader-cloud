"""Download long intraday history from Dukascopy (free) for scalp research:
   .venv\\Scripts\\python fetch_dukascopy.py EURUSD 730      -> models/duka_EURUSD_M15.pkl, models/duka_EURUSD_M5.pkl
"""
import logging
import os
import pickle
import sys
from datetime import datetime, timedelta

import dukascopy_python as dk
import pandas as pd
from dukascopy_python import instruments as ins

logging.disable(logging.CRITICAL)
INSTR = {"EURUSD": ins.INSTRUMENT_FX_MAJORS_EUR_USD, "GBPUSD": ins.INSTRUMENT_FX_MAJORS_GBP_USD, "USDJPY": ins.INSTRUMENT_FX_MAJORS_USD_JPY,
         "XAUUSD": getattr(ins, "INSTRUMENT_FX_METALS_XAU_USD", None), "BTCUSD": getattr(ins, "INSTRUMENT_VCCY_BTC_USD", None)}
for _n in dir(ins):                                   # any other pair by name, e.g. AUDUSD -> ..._AUD_USD
    if _n.startswith("INSTRUMENT_FX_") and _n.count("_") >= 4:
        INSTR.setdefault(_n.split("_")[-2] + _n.split("_")[-1], getattr(ins, _n))
OUT = os.path.join(os.path.dirname(__file__), "models")


def fetch(sym: str, interval, days: int, chunk_days: int = 30) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=days)
    parts, t = [], start
    while t < end:
        t2 = min(end, t + timedelta(days=chunk_days))
        for _ in range(3):
            try:
                parts.append(dk.fetch(INSTR[sym], interval, dk.OFFER_SIDE_BID, t, t2))
                break
            except Exception as e:  # noqa: BLE001
                print("retry", t.date(), e, flush=True)
        if __name__ == "__main__":
            print(sym, t.date(), "->", t2.date(), flush=True)
        t = t2
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index = pd.to_datetime(df.index, utc=True)
    return df[["open", "high", "low", "close", "volume"]]


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 730
    os.makedirs(OUT, exist_ok=True)
    ivs = {"M15": dk.INTERVAL_MIN_15, "M5": dk.INTERVAL_MIN_5, "H1": dk.INTERVAL_HOUR_1, "D1": dk.INTERVAL_DAY_1}
    names = sys.argv[3:] or ["M15", "M5"]
    for name, iv in ((n, ivs[n]) for n in names):
        df = fetch(sym, iv, days, 365 if name in ("H1", "D1") else 30)
        pickle.dump(df, open(os.path.join(OUT, f"duka_{sym}_{name}.pkl"), "wb"))
        print(f"saved {sym} {name}: {len(df)} bars {df.index[0]} -> {df.index[-1]}", flush=True)

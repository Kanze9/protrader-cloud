"""Long-history stats for the plan, per market and timeframe: H1 = 2 years (Yahoo), M15 = ~52 days (TradingView).

Run:  .venv\\Scripts\\python build_strategy_stats.py      (writes models/strategy_stats.json, ~1-2 minutes)
"""
import json
import logging
import os
import warnings

import pandas as pd
import yfinance as yf

import proplan
from config import INSTRUMENTS
from data_feed import load_ohlc

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
OUT = os.path.join(os.path.dirname(__file__), "models", "strategy_stats.json")


CACHE = os.path.join(os.path.dirname(__file__), "models", "yahoo_h1_cache.pkl")


def yahoo_h1(sym: str, ticker: str) -> pd.DataFrame:
    """2 years of H1 from Yahoo; Yahoo rate-limits, so fall back to the last saved copy."""
    import pickle
    cache = pickle.load(open(CACHE, "rb")) if os.path.exists(CACHE) else {}
    try:
        start = (pd.Timestamp.now() - pd.Timedelta(days=728)).strftime("%Y-%m-%d")
        d = yf.Ticker(ticker).history(start=start, interval="1h", auto_adjust=False)
        if d is not None and len(d) > 1000:
            d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
            d.index = pd.to_datetime(d.index, utc=True)
            cache[sym] = d
            pickle.dump(cache, open(CACHE, "wb"))
            return d
    except Exception:  # noqa: BLE001
        pass
    return cache[sym]


def main():
    stats = {}
    for sym, inst in INSTRUMENTS.items():
        for tf, getter, mins in (("H1", lambda: yahoo_h1(sym, inst.yf_ticker), 60), ("M15", lambda: load_ohlc(sym, "M15", 5000), 15)):
            try:
                df = getter()
                h4 = None if tf == "H1" else load_ohlc(sym, "H4", 5000)
                daily = None if tf == "H1" else load_ohlc(sym, "D1", 1000)
                h1 = None if tf == "H1" else load_ohlc(sym, "H1", 5000)
                from technical import add_indicators
                h1e = None
                if h1 is not None:
                    e = add_indicators(h1)["ema200"]
                    e.index = e.index + pd.Timedelta(hours=1)
                    tgt = df.index + pd.Timedelta(minutes=mins)
                    h1e = e.reindex(e.index.union(tgt)).ffill().reindex(tgt)
                    h1e.index = df.index
                for strat in ("pro", "v26"):
                  for strict in (False, True):
                    s = proplan.summary(proplan.trades(df, sym, mins, strat, h4=h4, h1_ema200=h1e, daily=daily, strict=strict))
                    if s:
                        s["from"], s["to"] = str(df.index[0])[:10], str(df.index[-1])[:10]
                        stats[f"{strat}{'_strict' if strict else ''}|{sym}|{tf}"] = s
                        print(f"{strat + ('_strict' if strict else ''):10s} {sym} {tf}: {s['n']} trades, win {s['win']:.0f}%, {s['avg_r']:+.3f}R/trade, PF {s['pf']:.2f}, "
                              f"total {s['total_r']:+.1f}R, maxDD {s['max_dd']:.1f}R  ({s['from']} -> {s['to']})", flush=True)
            except Exception as ex:  # noqa: BLE001
                print(sym, tf, "failed:", ex, flush=True)
    # high win-rate mode (mean reversion / small target), on the timeframe each was tested on
    import meanrev
    from tvDatafeed import Interval, TvDatafeed
    import data_feed
    if data_feed._tv_client is None:
        data_feed._tv_client = TvDatafeed()
    gold_d1 = data_feed._tv_client.get_hist("GOLD", "TVC", interval=Interval.in_daily, n_bars=5000)
    gold_d1.index = pd.to_datetime(gold_d1.index).tz_localize("UTC")
    for key, df_, sym, strat, kw in (("mr_d7|XAUUSD|D1", gold_d1, "XAUUSD", "mr_d7", {}),
                                     ("mr_rsi2|EURUSD|H1", yahoo_h1("EURUSD", "EURUSD=X"), "EURUSD", "mr_rsi2", {})):
        cfg = meanrev.exit_cfg(sym, strat)
        s = proplan.summary(meanrev.trades(df_, sym, strat, cfg["stop_atr"], tp1_r=cfg["tp1_r"]))
        s["from"], s["to"] = str(df_.index[0])[:10], str(df_.index[-1])[:10]
        stats[key] = s
        print(key, f"{s['n']} trades, win {s['win']:.0f}%, {s['avg_r']:+.3f}R, PF {s['pf']:.2f}", flush=True)
    duka = os.path.join(os.path.dirname(__file__), "models", "duka_EURUSD_H1.pkl")   # fetch_dukascopy.py EURUSD 3650 H1
    if os.path.exists(duka):
        h1 = pd.read_pickle(duka)
        h1 = h1[h1.volume > 0]
        pf = lambda x: float(x[x > 0].sum() / max(1e-9, -x[x < 0].sum()))
        for strat in ("mr_rsi2x", "mr_eur"):
            cfg = meanrev.exit_cfg("EURUSD", strat)
            gb_path = duka.replace("EURUSD", "GBPUSD")                                    # fetch_dukascopy.py GBPUSD 3650 H1
            peer = pd.read_pickle(gb_path) if strat == "mr_eur" and os.path.exists(gb_path) else None
            peer = peer[peer.volume > 0] if peer is not None else None
            tr = meanrev.trades(h1, "EURUSD", strat, cfg["stop_atr"], tp1_r=cfg["tp1_r"], peer=peer)
            s = proplan.summary(tr)
            r = pd.Series([t["r"] for t in tr if not t.get("open")])
            cut = int(len(r) * 0.6)
            s.update({"from": str(h1.index[0])[:10], "to": str(h1.index[-1])[:10], "pf_train": pf(r[:cut]), "pf_test": pf(r[cut:]),
                      "win_test": float((r[cut:] > 0).mean() * 100)})
            stats[f"{strat}|EURUSD|H1"] = s
            print(f"{strat}|EURUSD|H1", f"{s['n']} trades, win {s['win']:.0f}%, {s['avg_r']:+.3f}R, PF {s['pf']:.2f}", flush=True)
    s = proplan.summary(proplan.trades(yahoo_h1("BTCUSD", "BTC-USD"), "BTCUSD", 60, "v26", target_r=0.5))
    s["from"], s["to"] = "2024-10-24", str(pd.Timestamp.now())[:10]
    stats["v26_t05|BTCUSD|H1"] = s
    print("v26_t05|BTCUSD|H1", f"{s['n']} trades, win {s['win']:.0f}%, {s['avg_r']:+.3f}R, PF {s['pf']:.2f}", flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"built": str(pd.Timestamp.now(tz="UTC"))[:16], "stats": stats}, fh, indent=1)


if __name__ == "__main__":
    main()

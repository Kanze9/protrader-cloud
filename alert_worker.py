"""Background Gmail alerts for the tested plans (EURUSD, gold) - runs without the browser:  run_alerts.bat
   .venv\\Scripts\\python alert_worker.py           check every minute, email new signals / TP1 hits / exits
   .venv\\Scripts\\python alert_worker.py --test    email the latest EURUSD signal once (checks that Gmail works)
   .venv\\Scripts\\python alert_worker.py --dry     print the latest signal email of each market instead of sending it
"""
import json
import logging
import os
import sys
import time

import pandas as pd

import meanrev
import news as newsmod
from config import BARS, INSTRUMENTS
from data_feed import load_ohlc, load_tv_pair
from notify import alert_lot, email_ready, send_email, signal_email, update_email

# market, plan, dollar cross-check pair
MARKETS = [("EURUSD", "mr_eur", "GBPUSD"), ("XAUUSD", "mr_gold", "EURUSD")]
SYM, STRAT, PEER = MARKETS[0]                        # default market for --test
TF = "H1"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "models", "alert_state.json")
logging.basicConfig(filename=os.path.join(HERE, "alert_worker.log"), level=logging.INFO,
                    format="%(asctime)s %(message)s")
log = logging.getLogger("alerts")


def closed(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the candle that is still forming (signals use closed H1 candles only)."""
    now = pd.Timestamp.now(tz="UTC")
    return df[df.index + pd.Timedelta(hours=1) <= now]


def get_h1(sym: str):
    """H1 candles: TradingView (Pepperstone) first; Dukascopy if TradingView refuses (cloud servers); then Yahoo."""
    try:
        df = load_ohlc(sym, TF, BARS[TF]) if sym in INSTRUMENTS else load_tv_pair(sym, TF, BARS[TF])
        if df is not None and len(df) > 300:
            return df
    except Exception as e:  # noqa: BLE001
        log.info("TradingView %s failed: %s", sym, e)
    try:
        from dukascopy_python import INTERVAL_HOUR_1
        from fetch_dukascopy import fetch
        df = fetch(sym, INTERVAL_HOUR_1, 160, 365)              # enough for the 50-day trend filter
        if len(df) > 300:
            return df[df.volume > 0]
    except Exception as e:  # noqa: BLE001
        log.info("Dukascopy %s failed: %s", sym, e)
    return None


def plan_trades(sym: str = SYM, strat: str = STRAT, peer_sym: str = PEER, with_checks: bool = False):
    d = get_h1(sym)
    if d is None:
        raise RuntimeError(f"no {sym} data from TradingView, Dukascopy or Yahoo")
    d = closed(d)
    peer = get_h1(peer_sym)
    peer = closed(peer) if peer is not None else None
    cfg = meanrev.exit_cfg(sym, strat)
    trades = meanrev.trades(d, sym, strat, cfg["stop_atr"], tp1_r=cfg["tp1_r"], peer=peer)
    if not with_checks:
        return trades, d.index[-1], peer is not None
    dm = meanrev.prepare(d)
    if peer is not None:
        dm["usd_wide"] = meanrev.usd_wide(dm, peer)
    if strat == "mr_gold":
        meanrev.add_daily_trend(dm)
    chk = meanrev.checks(dm, len(dm) - 1, strat)
    chk["price"], chk["time"] = float(dm.close.iloc[-1]), dm.index[-1]
    return trades, d.index[-1], peer is not None, chk


def stats(sym: str = SYM, strat: str = STRAT):
    try:
        with open(os.path.join(HERE, "models", "strategy_stats.json"), encoding="utf-8") as fh:
            return json.load(fh)["stats"].get(f"{strat}|{sym}|H1")
    except (OSError, ValueError, KeyError):
        return None


def news_soon(sym: str = SYM):
    try:
        now = pd.Timestamp.now(tz="UTC")
        return [x for x in newsmod.relevant_events(newsmod.fetch_calendar(), sym)
                if x["impact"] == "High" and now - pd.Timedelta(minutes=15) <= x["time"] <= now + pd.Timedelta(minutes=60)]
    except Exception:  # noqa: BLE001
        return []


def load_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_state(st):
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=1)


def entry_mail(t, sym: str = SYM, strat: str = STRAT):
    return signal_email(sym, t, stats(sym, strat), alert_lot(), news_soon(sym))


def check_market(st, sym, strat, result, send):
    """Email new entries / TP1 hits / exits of one market once each."""
    trades, last_bar, peer_ok = result[:3]
    if not peer_ok:
        log.info("%s: cross-check pair unavailable - dollar filter off this round", sym)
    if sym == "EURUSD" and "entries" in st:                      # state from the EURUSD-only version
        st.setdefault("EURUSD", {})["entries"] = st.pop("entries")
    sent = st.setdefault(sym, {}).setdefault("entries", {})
    for t in trades:
        tid = str(t["time"])
        info = sent.get(tid)
        if info is None:
            # only signals from the last two closed candles are worth entering
            if t["time"] >= last_bar - pd.Timedelta(hours=1) and t.get("open"):
                send(*entry_mail(t, sym, strat))
                log.info("sent entry %s %s %s", sym, tid, t["side"])
            sent[tid] = {"tp1": t.get("tp1_time") is not None, "closed": not t.get("open")}
            continue
        if t.get("tp1_time") is not None and not info["tp1"]:
            send(*update_email(sym, t, "tp1"))
            info["tp1"] = True
            log.info("sent tp1 %s %s", sym, tid)
        if not t.get("open") and not info["closed"]:
            send(*update_email(sym, t, "closed"))
            info["closed"] = True
            log.info("sent close %s %s %+.2fR", sym, tid, t["r"])
    return trades


def check_once(st, send=None, results=None):
    """All markets. `results` maps symbol -> plan_trades output, so a caller can reuse data it already loaded."""
    send = send or send_email
    for sym, strat, peer_sym in MARKETS:
        try:
            res = (results or {}).get(sym) or plan_trades(sym, strat, peer_sym)
            check_market(st, sym, strat, res, send)
        except Exception as e:  # noqa: BLE001 - one market failing must not stop the other
            log.warning("%s check failed: %s", sym, e)


def main():
    if "--dry" in sys.argv:
        for sym, strat, peer_sym in MARKETS:
            trades, _, _ = plan_trades(sym, strat, peer_sym)
            if trades:
                subject, text, _ = entry_mail(trades[-1], sym, strat)
                print(subject + "\n\n" + text + "\n" + "-" * 70)
        return
    if "--test" in sys.argv:
        trades, _, _ = plan_trades()
        subject, text, html_body = entry_mail(trades[-1])
        send_email("[TEST] " + subject, "This is a test with the latest signal.\n\n" + text, html_body)
        print("Test email sent to", os.getenv("ALERT_EMAIL_TO") or os.getenv("GMAIL_USER"))
        return
    if not email_ready():
        raise SystemExit("Gmail is not set up - run:  .venv\\Scripts\\python set_email.py")
    st = load_state() or {}
    print("Gmail alerts running for", ", ".join(m[0] for m in MARKETS), "(checks every 60 s). Close this window to stop.")
    while True:
        check_once(st)
        save_state(st)
        time.sleep(60)


if __name__ == "__main__":
    main()

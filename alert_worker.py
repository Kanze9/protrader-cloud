"""Background Gmail alerts for the EURUSD plan - runs without the browser:  run_alerts.bat
   .venv\\Scripts\\python alert_worker.py           check every minute, email new signals / TP1 hits / exits
   .venv\\Scripts\\python alert_worker.py --test    email the latest signal once (checks that Gmail works)
   .venv\\Scripts\\python alert_worker.py --dry     print the latest signal email instead of sending it
"""
import json
import logging
import os
import sys
import time

import pandas as pd

import meanrev
import news as newsmod
from config import BARS
from data_feed import load_ohlc, load_tv_pair
from notify import alert_lot, email_ready, send_email, signal_email, update_email

SYM, STRAT, TF = "EURUSD", "mr_eur", "H1"
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
        df = load_ohlc(sym, TF, BARS[TF]) if sym == SYM else load_tv_pair(sym, TF, BARS[TF])
        if df is not None and len(df) > 300:
            return df
    except Exception as e:  # noqa: BLE001
        log.info("TradingView %s failed: %s", sym, e)
    try:
        from dukascopy_python import INTERVAL_HOUR_1
        from fetch_dukascopy import fetch
        df = fetch(sym, INTERVAL_HOUR_1, 110, 365)
        if len(df) > 300:
            return df[df.volume > 0]
    except Exception as e:  # noqa: BLE001
        log.info("Dukascopy %s failed: %s", sym, e)
    return None


def plan_trades(with_checks: bool = False):
    d = get_h1(SYM)
    if d is None:
        raise RuntimeError("no EURUSD data from TradingView, Dukascopy or Yahoo")
    d = closed(d)
    peer = get_h1("GBPUSD")
    peer = closed(peer) if peer is not None else None
    cfg = meanrev.exit_cfg(SYM, STRAT)
    trades = meanrev.trades(d, SYM, STRAT, cfg["stop_atr"], tp1_r=cfg["tp1_r"], peer=peer)
    if not with_checks:
        return trades, d.index[-1], peer is not None
    dm = meanrev.prepare(d)
    if peer is not None:
        dm["usd_wide"] = meanrev.usd_wide(dm, peer)
    chk = meanrev.checks(dm, len(dm) - 1, STRAT)
    chk["price"], chk["time"] = float(dm.close.iloc[-1]), dm.index[-1]
    return trades, d.index[-1], peer is not None, chk


def stats():
    try:
        with open(os.path.join(HERE, "models", "strategy_stats.json"), encoding="utf-8") as fh:
            return json.load(fh)["stats"].get(f"{STRAT}|{SYM}|H1")
    except (OSError, ValueError, KeyError):
        return None


def news_soon():
    try:
        now = pd.Timestamp.now(tz="UTC")
        return [x for x in newsmod.relevant_events(newsmod.fetch_calendar(), SYM)
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


def entry_mail(t):
    return signal_email(SYM, t, stats(), alert_lot(), news_soon())


def check_once(st, send=None, result=None):
    """Email new entries / TP1 hits / exits once each. `result` lets a caller reuse already-loaded plan_trades output."""
    send = send or send_email
    trades, last_bar, peer_ok = (result or plan_trades())[:3]
    if not peer_ok:
        log.info("GBPUSD unavailable - dollar filter off this round")
    sent = st.setdefault("entries", {})
    for t in trades:
        tid = str(t["time"])
        info = sent.get(tid)
        if info is None:
            # only signals from the last two closed candles are worth entering
            if t["time"] >= last_bar - pd.Timedelta(hours=1) and t.get("open"):
                send(*entry_mail(t))
                log.info("sent entry %s %s", tid, t["side"])
            sent[tid] = {"tp1": t.get("tp1_time") is not None, "closed": not t.get("open")}
            continue
        if t.get("tp1_time") is not None and not info["tp1"]:
            send(*update_email(SYM, t, "tp1"))
            info["tp1"] = True
            log.info("sent tp1 %s", tid)
        if not t.get("open") and not info["closed"]:
            send(*update_email(SYM, t, "closed"))
            info["closed"] = True
            log.info("sent close %s %+.2fR", tid, t["r"])
    return trades


def main():
    if "--dry" in sys.argv or "--test" in sys.argv:
        trades, _, _ = plan_trades()
        t = trades[-1]
        subject, text, html_body = entry_mail(t)
        if "--dry" in sys.argv:
            print(subject + "\n\n" + text)
            return
        send_email("[TEST] " + subject, "This is a test with the latest signal.\n\n" + text, html_body)
        print("Test email sent to", os.getenv("ALERT_EMAIL_TO") or os.getenv("GMAIL_USER"))
        return
    if not email_ready():
        raise SystemExit("Gmail is not set up - run:  .venv\\Scripts\\python set_email.py")
    st = load_state() or {}
    print("Gmail alerts running for EURUSD (checks every 60 s). Close this window to stop.")
    while True:
        try:
            check_once(st)
            save_state(st)
        except Exception as e:  # noqa: BLE001 - keep running through network hiccups
            log.warning("check failed: %s", e)
        time.sleep(60)


if __name__ == "__main__":
    main()

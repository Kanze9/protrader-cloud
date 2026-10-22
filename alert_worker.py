"""Background Gmail alerts for every tested plan (plans.PLANS: tier A high accuracy, tier B trend) - runs without the browser.
   .venv\\Scripts\\python alert_worker.py           check every minute, email new signals / TP1 hits / exits
   .venv\\Scripts\\python alert_worker.py --test    email the latest EURUSD signal once (checks that Gmail works)
   .venv\\Scripts\\python alert_worker.py --dry     print the latest signal email of each plan instead of sending it
"""
import json
import logging
import os
import sys
import time

import pandas as pd

import news as newsmod
import plans
from config import BARS, INSTRUMENTS, TIMEFRAMES
from data_feed import load_ohlc, load_tv_pair
from notify import alert_lot, email_ready, send_email, signal_email, update_email

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "models", "alert_state.json")
logging.basicConfig(filename=os.path.join(HERE, "alert_worker.log"), level=logging.INFO,
                    format="%(asctime)s %(message)s")
log = logging.getLogger("alerts")
OLD_KEYS = {"EURUSD": "eur_a", "XAUUSD": "gold_a"}          # state from the per-market version


def closed(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Drop the candle that is still forming (signals use closed candles only)."""
    now = pd.Timestamp.now(tz="UTC")
    return df[df.index + pd.Timedelta(minutes=TIMEFRAMES[tf][1]) <= now]


def make_getter():
    """get(symbol, tf) -> closed candles, cached for one round: TradingView (Pepperstone) first, Dukascopy if refused."""
    cache = {}

    def get(sym: str, tf: str):
        if (sym, tf) in cache:
            return cache[(sym, tf)]
        df = None
        try:
            df = load_ohlc(sym, tf, BARS[tf]) if sym in INSTRUMENTS else load_tv_pair(sym, tf, BARS[tf])
        except Exception as e:  # noqa: BLE001
            log.info("TradingView %s %s failed: %s", sym, tf, e)
        if df is None or len(df) < 300:
            try:
                import dukascopy_python as dk
                from fetch_dukascopy import fetch
                iv = {"H1": dk.INTERVAL_HOUR_1, "M15": dk.INTERVAL_MIN_15}[tf]
                df = fetch(sym, iv, 160 if tf == "H1" else 30, 365 if tf == "H1" else 30)
                df = df[df.volume > 0]
            except Exception as e:  # noqa: BLE001
                log.info("Dukascopy %s %s failed: %s", sym, tf, e)
                df = None
        cache[(sym, tf)] = closed(df, tf) if df is not None and len(df) else None
        return cache[(sym, tf)]
    return get


def news_soon(sym: str):
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


def entry_mail(res: dict, t: dict):
    p = res["plan"]
    return signal_email(p["sym"], t, res["stats"], alert_lot(), news_soon(p["sym"]), tf_minutes=TIMEFRAMES[p["tf"]][1], plan=p)


def check_plan(st, res, send):
    """Email new entries / TP1 hits / exits of one plan once each."""
    p = res["plan"]
    if "entries" in st:                                           # oldest format: EURUSD only
        st.setdefault("EURUSD", {})["entries"] = st.pop("entries")
    for old, new in OLD_KEYS.items():
        if old in st and new not in st:
            st[new] = st.pop(old)
    sent = st.setdefault(p["id"], {}).setdefault("entries", {})
    fresh_from = res["time"] - pd.Timedelta(minutes=TIMEFRAMES[p["tf"]][1])      # last two closed candles
    for t in res["trades"]:
        tid = str(t["time"])
        info = sent.get(tid)
        if info is None:
            if t["time"] >= fresh_from and t.get("open"):
                send(*entry_mail(res, t))
                log.info("sent entry %s %s %s", p["id"], tid, t["side"])
            sent[tid] = {"tp1": t.get("tp1_time") is not None, "closed": not t.get("open")}
            continue
        if t.get("tp1_time") is not None and not info["tp1"]:
            send(*update_email(p["sym"], t, "tp1", p))
            info["tp1"] = True
            log.info("sent tp1 %s %s", p["id"], tid)
        if not t.get("open") and not info["closed"]:
            send(*update_email(p["sym"], t, "closed", p))
            info["closed"] = True
            log.info("sent close %s %s %+.2fR", p["id"], tid, t["r"])


def run_all(get=None):
    """Every plan's result (plans.run_plan); a plan that fails is reported as {"plan", "error"}."""
    get = get or make_getter()
    out = []
    for p in plans.PLANS:
        try:
            out.append(plans.run_plan(p, get))
        except Exception as e:  # noqa: BLE001 - one plan failing must not stop the others
            log.warning("%s failed: %s", p["id"], e)
            out.append({"plan": p, "error": str(e)})
    return out


def check_once(st, send=None, results=None):
    send = send or send_email
    for res in results or run_all():
        if "error" not in res:
            check_plan(st, res, send)


def main():
    if "--dry" in sys.argv:
        for res in run_all():
            if "error" in res:
                print(res["plan"]["id"], "ERROR", res["error"])
            elif res["trades"]:
                subject, text, _ = entry_mail(res, res["trades"][-1])
                print(subject + "\n\n" + text + "\n" + "-" * 70)
        return
    if "--test" in sys.argv:
        res = plans.run_plan(plans.PLANS[0], make_getter())
        subject, text, html_body = entry_mail(res, res["trades"][-1])
        send_email("[TEST] " + subject, "This is a test with the latest signal.\n\n" + text, html_body)
        print("Test email sent to", os.getenv("ALERT_EMAIL_TO") or os.getenv("GMAIL_USER"))
        return
    if not email_ready():
        raise SystemExit("Gmail is not set up - run:  .venv\\Scripts\\python set_email.py")
    st = load_state() or {}
    print("Gmail alerts running for", len(plans.PLANS), "plans (checks every 60 s). Close this window to stop.")
    while True:
        check_once(st)
        save_state(st)
        time.sleep(60)


if __name__ == "__main__":
    main()

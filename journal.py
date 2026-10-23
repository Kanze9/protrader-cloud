"""Paper-trading journal: log every signal and check later whether TP or SL was hit first."""
import json
import os
from datetime import datetime, timezone

import pandas as pd

PATH = os.path.join(os.path.dirname(__file__), "signal_journal.csv")
COLS = ["time", "symbol", "tf", "engine", "decision", "confidence", "entry", "stop_loss",
        "tp1", "tp2", "tp3", "outcome", "r_multiple", "summary"]


def load() -> pd.DataFrame:
    if not os.path.exists(PATH):
        return pd.DataFrame(columns=COLS)
    df = pd.read_csv(PATH)
    df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601")
    return df


def log_signal(symbol: str, tf: str, sig: dict) -> None:
    if sig.get("decision") not in ("LONG", "SHORT"):
        return
    row = {c: sig.get(c) for c in COLS}
    row.update(time=datetime.now(timezone.utc).isoformat(), symbol=symbol, tf=tf, outcome="OPEN", r_multiple=None)
    df = pd.concat([load(), pd.DataFrame([row])], ignore_index=True)
    df.to_csv(PATH, index=False)


def evaluate(row, candles: pd.DataFrame):
    """Simulate the trade on candles after the signal (market entry assumed).

    Management: 1/3 closed at each TP, stop moved to break-even once TP1 fills.
    Conservative: if the stop and a target are inside the same candle, the stop counts first.
    Returns (outcome label, realised R multiple or None while open).
    """
    after = candles[candles.index > row["time"]]
    long = row["decision"] == "LONG"
    e, stop = float(row["entry"]), float(row["stop_loss"])
    risk = abs(e - stop) or 1e-9
    tps = [float(row["tp1"]), float(row["tp2"]), float(row["tp3"])]
    filled, realised = 0, 0.0
    for _, c in after.iterrows():
        if (c.low <= stop) if long else (c.high >= stop):
            realised += (1 - filled / 3) * ((stop - e) if long else (e - stop)) / risk
            return ("SL" if filled == 0 else f"TP{filled} then BE"), round(realised, 2)
        while filled < 3 and ((c.high >= tps[filled]) if long else (c.low <= tps[filled])):
            realised += abs(tps[filled] - e) / risk / 3
            filled += 1
            stop = e  # break-even after first target
        if filled == 3:
            return "TP3", round(realised, 2)
    return (f"TP{filled} (running)" if filled else "OPEN"), None


def save(df: pd.DataFrame) -> None:
    df.to_csv(PATH, index=False)

"""Macro board: dollar, yields, volatility, equities, oil, silver -> risk mood for the AI and the UI."""
import logging
from typing import Dict, List

import pandas as pd

import data_feed

log = logging.getLogger(__name__)

# (label, TradingView exchange, symbol)
BOARD = [("DXY", "TVC", "DXY"), ("US10Y", "TVC", "US10Y"), ("VIX", "TVC", "VIX"),
         ("S&P 500", "PEPPERSTONE", "US500"), ("WTI oil", "TVC", "USOIL"), ("Silver", "PEPPERSTONE", "XAGUSD")]


def _hist(exchange: str, symbol: str, bars: int = 40):
    from tvDatafeed import Interval, TvDatafeed
    if data_feed._tv_client is None:
        data_feed._tv_client = TvDatafeed()
    return data_feed._tv_client.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_1_hour, n_bars=bars)


def fetch_board() -> List[Dict]:
    out = []
    for label, ex, sym in BOARD:
        try:
            df = _hist(ex, sym)
            if df is None or len(df) < 25:
                continue
            c = df["close"]
            out.append({"name": label, "last": float(c.iloc[-1]),
                        "chg_1h": float((c.iloc[-1] / c.iloc[-2] - 1) * 100),
                        "chg_24h": float((c.iloc[-1] / c.iloc[-25] - 1) * 100)})
        except Exception as e:  # noqa: BLE001
            log.warning("macro %s failed: %s", sym, e)
    return out


def risk_mood(board: List[Dict]) -> Dict:
    """Classic cross-asset read: stocks up + VIX down = risk-on; the reverse = risk-off."""
    b = {x["name"]: x for x in board}
    score = 0.0
    if "S&P 500" in b:
        score += max(-1, min(1, b["S&P 500"]["chg_24h"] / 0.6))
    if "VIX" in b:
        score -= max(-1, min(1, b["VIX"]["chg_24h"] / 6))
    mood = "risk-on" if score > 0.6 else "risk-off" if score < -0.6 else "mixed"
    return {"score": round(score, 2), "mood": mood}


def board_text(board: List[Dict]) -> str:
    if not board:
        return ""
    m = risk_mood(board)
    parts = [f"{x['name']} {x['last']:.2f} ({x['chg_24h']:+.2f}% 24h, {x['chg_1h']:+.2f}% 1h)" for x in board]
    return f"Macro board: {'; '.join(parts)}. Cross-asset mood: {m['mood']} (score {m['score']:+.2f})."

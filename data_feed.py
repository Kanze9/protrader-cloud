"""Market data: TradingView (PEPPERSTONE feed) -> MT5 (Pepperstone) -> Yahoo fallback.

All loaders return a DataFrame indexed by UTC timestamp with columns
open, high, low, close, volume, plus df.attrs["source"].
"""
import logging
from datetime import datetime, timezone

import pandas as pd

from config import INSTRUMENTS, TIMEFRAMES

log = logging.getLogger(__name__)

SOURCES = ["TradingView (Pepperstone)", "MT5 (Pepperstone terminal)", "Yahoo Finance"]

_tv_client = None


def _finish(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index().dropna()
    if df.index.tz is None:
        df.index = df.index.tz_localize(timezone.utc)
    else:
        df.index = df.index.tz_convert(timezone.utc)
    df.attrs["source"] = source
    return df


def _load_tradingview(symbol: str, tf: str, bars: int) -> pd.DataFrame:
    global _tv_client
    from tvDatafeed import Interval, TvDatafeed

    intervals = {
        "M5": Interval.in_5_minute, "M15": Interval.in_15_minute, "H1": Interval.in_1_hour,
        "H4": Interval.in_4_hour, "D1": Interval.in_daily,
    }
    inst = INSTRUMENTS[symbol]
    df = None
    for _ in range(3):  # the anonymous websocket drops now and then: retry with a fresh client
        if _tv_client is None:
            _tv_client = TvDatafeed()
        df = _tv_client.get_hist(symbol=inst.tv_symbol, exchange="PEPPERSTONE",
                                 interval=intervals[tf], n_bars=bars)
        if df is not None and not df.empty:
            break
        _tv_client = None
    if df is None or df.empty:
        raise RuntimeError("TradingView returned no data")
    # TradingView timestamps come back in this machine's local time without tz info
    offset = datetime.now().astimezone().utcoffset()
    df.index = (pd.to_datetime(df.index) - offset).tz_localize("UTC")
    return _finish(df, "TradingView · PEPPERSTONE")


def _load_mt5(symbol: str, tf: str, bars: int) -> pd.DataFrame:
    import MetaTrader5 as mt5

    frames = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
              "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    inst = INSTRUMENTS[symbol]
    mt5.symbol_select(inst.mt5_symbol, True)
    rates = mt5.copy_rates_from_pos(inst.mt5_symbol, frames[tf], 0, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"MT5 returned no data: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={"tick_volume": "volume"})
    return _finish(df, "MT5 · Pepperstone")


def _load_yahoo(symbol: str, tf: str, bars: int) -> pd.DataFrame:
    import yfinance as yf

    inst = INSTRUMENTS[symbol]
    if tf == "M5":
        interval, period = "5m", "15d"
    elif tf == "M15":
        interval, period = "15m", "30d"
    elif tf in ("H1", "H4"):
        interval, period = "1h", "200d"
    else:
        interval, period = "1d", "5y"
    df = yf.Ticker(inst.yf_ticker).history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError("Yahoo returned no data")
    df = df.rename(columns=str.lower)
    if tf == "H4":
        df = df.resample("4h", origin="epoch").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
    note = "" if inst.yf_ticker.endswith("=X") or inst.yf_ticker.startswith("BTC") else " (futures proxy)"
    return _finish(df.tail(bars), f"Yahoo Finance{note}")


_LOADERS = {
    SOURCES[0]: _load_tradingview,
    SOURCES[1]: _load_mt5,
    SOURCES[2]: _load_yahoo,
}


def live_quote(symbol: str, preferred: str = SOURCES[0]):
    """Latest price for the live ticker: a real tick from the MT5 terminal when that source is chosen,
    otherwise the last 1-minute candle from TradingView (about 1 s per call). None when unavailable."""
    global _tv_client
    inst = INSTRUMENTS[symbol]
    try:
        if preferred == SOURCES[1]:
            import MetaTrader5 as mt5
            if mt5.initialize():
                tk = mt5.symbol_info_tick(inst.mt5_symbol)
                if tk:
                    return {"price": (tk.bid + tk.ask) / 2, "bid": tk.bid, "ask": tk.ask,
                            "time": pd.Timestamp(tk.time, unit="s", tz="UTC"), "src": "MT5 tick"}
        from tvDatafeed import Interval, TvDatafeed
        if _tv_client is None:
            _tv_client = TvDatafeed()
        df = _tv_client.get_hist(symbol=inst.tv_symbol, exchange="PEPPERSTONE", interval=Interval.in_1_minute, n_bars=2)
        if df is None or df.empty:
            _tv_client = None
            return None
        t = (pd.Timestamp(df.index[-1]) - datetime.now().astimezone().utcoffset()).tz_localize("UTC")
        return {"price": float(df.close.iloc[-1]), "time": t, "src": "TradingView M1"}
    except Exception:  # noqa: BLE001
        return None


def load_ohlc(symbol: str, tf: str, bars: int = 500, preferred: str = SOURCES[0]) -> pd.DataFrame:
    """Load candles, trying the preferred source first and falling back down the list."""
    if tf not in TIMEFRAMES:
        raise ValueError(f"Unknown timeframe {tf}")
    order = [preferred] + [s for s in SOURCES if s != preferred]
    errors = []
    for src in order:
        try:
            df = _LOADERS[src](symbol, tf, bars)
            if len(df) >= 60:
                if src != preferred:
                    df.attrs["source"] += f" (fallback: {preferred} failed)"
                return df
            errors.append(f"{src}: only {len(df)} bars")
        except Exception as e:  # noqa: BLE001 - try the next source
            log.warning("%s failed for %s %s: %s", src, symbol, tf, e)
            errors.append(f"{src}: {e}")
    raise RuntimeError("All data sources failed:\n" + "\n".join(errors))


# Intermarket drivers per instrument: (TradingView exchange, symbol, expected sign of the relationship)
INTERMARKET = {
    "XAUUSD": ("TVC", "DXY", -1),
    "EURUSD": ("TVC", "DXY", -1),
    "GBPUSD": ("TVC", "DXY", -1),
    "USDJPY": ("TVC", "US10Y", 1),
    "BTCUSD": ("PEPPERSTONE", "NAS100", 1),
    "NAS100": ("TVC", "US10Y", -1),
}


def load_tv_pair(tv_symbol: str, tf: str, bars: int = 1500, exchange: str = "PEPPERSTONE"):
    """Any TradingView symbol (e.g. GBPUSD as the USD cross-check for EURUSD). None when unavailable."""
    global _tv_client
    try:
        from tvDatafeed import Interval, TvDatafeed
        iv = {"M5": Interval.in_5_minute, "M15": Interval.in_15_minute, "H1": Interval.in_1_hour,
              "H4": Interval.in_4_hour, "D1": Interval.in_daily}[tf]
        for _ in range(3):
            if _tv_client is None:
                _tv_client = TvDatafeed()
            df = _tv_client.get_hist(symbol=tv_symbol, exchange=exchange, interval=iv, n_bars=bars)
            if df is not None and not df.empty:
                offset = datetime.now().astimezone().utcoffset()
                df.index = (pd.to_datetime(df.index) - offset).tz_localize("UTC")
                return _finish(df, f"TradingView · {exchange}")
            _tv_client = None
    except Exception as e:  # noqa: BLE001
        log.warning("pair %s failed: %s", tv_symbol, e)
    return None


def load_intermarket(symbol: str, tf: str, bars: int = 600):
    """Driver series (e.g. DXY for gold) from TradingView; returns (name, sign, df) or None."""
    global _tv_client
    if symbol not in INTERMARKET:
        return None
    exchange, sym, sign = INTERMARKET[symbol]
    try:
        from tvDatafeed import Interval, TvDatafeed
        iv = {"M5": Interval.in_5_minute, "M15": Interval.in_15_minute, "H1": Interval.in_1_hour,
              "H4": Interval.in_4_hour, "D1": Interval.in_daily}[tf]
        if _tv_client is None:
            _tv_client = TvDatafeed()
        df = _tv_client.get_hist(symbol=sym, exchange=exchange, interval=iv, n_bars=bars)
        if df is None or df.empty:
            return None
        offset = datetime.now().astimezone().utcoffset()
        df.index = (pd.to_datetime(df.index) - offset).tz_localize("UTC")
        return sym, sign, _finish(df, f"TradingView · {exchange}")
    except Exception as e:  # noqa: BLE001
        log.warning("intermarket %s failed: %s", sym, e)
        return None

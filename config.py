"""Instrument definitions and app-wide settings."""
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Instrument:
    name: str                 # display / Pepperstone symbol
    tv_symbol: str            # TradingView symbol on the PEPPERSTONE exchange
    yf_ticker: str            # Yahoo Finance fallback ticker
    mt5_symbol: str           # Pepperstone MT5 symbol
    contract_size: float      # units per 1.0 lot
    pip: float                # one pip in price terms
    digits: int
    quote_ccy: str            # currency the P/L is denominated in
    base_ccy: str
    default_leverage: int
    news_keywords: List[str] = field(default_factory=list)
    calendar_ccys: List[str] = field(default_factory=list)


INSTRUMENTS = {
    "XAUUSD": Instrument(
        "XAUUSD", "XAUUSD", "GC=F", "XAUUSD", 100, 0.1, 2, "USD", "XAU", 500,
        ["gold", "xau", "bullion", "fed", "powell", "inflation", "cpi", "yields",
         "treasury", "dollar", "dxy", "geopolit", "war", "safe haven", "central bank", "trump", "tariff"],
        ["USD"]),
    "BTCUSD": Instrument(
        "BTCUSD", "BTCUSD", "BTC-USD", "BTCUSD", 1, 1.0, 2, "USD", "BTC", 500,
        ["bitcoin", "btc", "crypto", "etf", "sec", "stablecoin", "blackrock",
         "halving", "fed", "risk appetite", "nasdaq", "liquidat", "trump", "tariff"],
        ["USD"]),
    "EURUSD": Instrument(
        "EURUSD", "EURUSD", "EURUSD=X", "EURUSD", 100_000, 0.0001, 5, "USD", "EUR", 500,
        ["eur", "euro", "ecb", "lagarde", "eurozone", "germany", "fed", "powell",
         "dollar", "dxy", "cpi", "nfp", "payrolls", "pmi", "tariff", "trump", "tariff"],
        ["EUR", "USD"]),
    "USDJPY": Instrument(
        "USDJPY", "USDJPY", "JPY=X", "USDJPY", 100_000, 0.01, 3, "JPY", "USD", 500,
        ["yen", "jpy", "boj", "ueda", "japan", "intervention", "fed", "powell",
         "dollar", "yields", "treasury", "carry", "trump", "tariff"],
        ["JPY", "USD"]),
}

# timeframe key -> (label, minutes)
TIMEFRAMES = {
    "M5": ("5 min", 5),
    "M15": ("15 min", 15),
    "H1": ("1 hour", 60),
    "H4": ("4 hours", 240),
    "D1": ("Daily", 1440),
}

# Higher timeframes analysed alongside the chosen one (top-down analysis)
MTF_STACK = {
    "M5": ["M5", "M15", "H1"],
    "M15": ["M15", "H1", "H4"],
    "H1": ["H1", "H4", "D1"],
    "H4": ["H4", "D1"],
    "D1": ["D1"],
}

# Candles to load per timeframe (intraday needs enough for previous-day levels and VWAP)
BARS = {"M5": 1200, "M15": 2000, "H1": 3000, "H4": 500, "D1": 400}

# Typical Pepperstone Razor all-in cost (spread + commission) in price units.
# Used to pad stops and to show the real cost of a scalp in R.
SPREADS = {"XAUUSD": 0.20, "BTCUSD": 20.0, "EURUSD": 0.00009, "USDJPY": 0.012,
           "GBPUSD": 0.00012, "NAS100": 1.2}

# AI brain: DeepSeek through the user's OpenAI-compatible relay (DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL in .env)
AI_PROVIDERS = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "json_mode": False,
    },
}
AI_PROVIDER = "DeepSeek"

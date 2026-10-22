"""Position sizing and margin for CFD/FX at a given leverage."""
from typing import Dict

from config import INSTRUMENTS

MIN_LOT, LOT_STEP = 0.01, 0.01   # Pepperstone minimum and step


def to_usd(amount_quote: float, symbol: str, price: float) -> float:
    """Convert a P/L amount in the instrument's quote currency to USD."""
    inst = INSTRUMENTS[symbol]
    if inst.quote_ccy == "USD":
        return amount_quote
    if inst.base_ccy == "USD":          # e.g. USDJPY: JPY -> USD
        return amount_quote / price
    return amount_quote


def position_size(symbol: str, entry: float, stop: float, balance: float,
                  risk_pct: float, leverage: int, fixed_lots: float = 0.0) -> Dict:
    """Lot size from the risk %, or the trader's own lot size when fixed_lots > 0 (then the risk follows from it)."""
    inst = INSTRUMENTS[symbol]
    dist = abs(entry - stop)
    if dist <= 0 or balance <= 0:
        return {"lots": 0.0, "risk_usd": 0.0, "margin_usd": 0.0, "warnings": ["invalid stop"], "tradeable": False}
    target_risk = balance * risk_pct / 100
    loss_per_lot = to_usd(dist * inst.contract_size, symbol, entry)
    raw = target_risk / loss_per_lot
    lots = int(raw / LOT_STEP + 1e-9) * LOT_STEP
    if fixed_lots > 0:
        lots = max(MIN_LOT, round(fixed_lots / LOT_STEP) * LOT_STEP)
    warnings = []
    forced = lots < MIN_LOT
    if forced:
        lots = MIN_LOT
    lots = round(lots, 2)
    risk_usd = lots * loss_per_lot
    actual_pct = round(100 * risk_usd / balance, 2)
    notional_usd = lots * inst.contract_size * (entry if inst.base_ccy != "USD" else 1)
    margin = notional_usd / leverage
    if forced and not fixed_lots:
        warnings.append(f"Minimum lot 0.01 risks {actual_pct:.1f}% of the account (target {risk_pct}%).")
    if actual_pct > 5:
        warnings.append("Risk above 5% per trade - skip this setup or use a tighter one.")
    if margin > balance * 0.9:
        warnings.append(f"Not enough margin: needs ${margin:,.2f}, balance ${balance:,.2f}.")
    return {
        "lots": lots,
        "risk_usd": round(risk_usd, 2),
        "actual_risk_pct": round(actual_pct, 2),
        "sl_pips": round(dist / inst.pip, 1),
        "pip_value_per_lot_usd": round(to_usd(inst.pip * inst.contract_size, symbol, entry), 4),
        "pip_value_usd": round(lots * to_usd(inst.pip * inst.contract_size, symbol, entry), 2),
        "fixed": bool(fixed_lots),
        "margin_usd": round(margin, 2),
        "margin_pct_of_balance": round(100 * margin / balance, 2),
        "effective_leverage": round(notional_usd / balance, 1),
        "warnings": warnings,
        "tradeable": actual_pct <= 5 and margin <= balance * 0.9,
    }


def reward_usd(symbol: str, entry: float, target: float, lots: float) -> float:
    inst = INSTRUMENTS[symbol]
    return round(to_usd(abs(target - entry) * inst.contract_size * lots, symbol, entry), 2)

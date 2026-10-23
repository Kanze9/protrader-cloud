"""The 'pro trader brain': rule-based signal + DeepSeek synthesis (OpenAI-compatible API)."""
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from dotenv import load_dotenv

from config import AI_PROVIDERS, INSTRUMENTS
from technical import TFAnalysis, mtf_score, to_prompt_text

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

SYSTEM_PROMPT = """You are a senior discretionary trader and risk manager with 20 years of experience
trading gold, FX majors, indices and crypto CFDs. You think like a professional prop-desk trader:

METHOD (apply all of it, top-down):
1. Higher-timeframe bias first (D1/H4), then refine entries on the lower timeframe.
2. Market structure: HH/HL vs LH/LL, breaks of structure (BOS), change of character (CHoCH).
3. Smart-money concepts: liquidity pools (equal highs/lows, recent extremes), stop hunts / sweeps,
   order blocks, unfilled fair value gaps as magnets and entry zones, premium vs discount (50% of range).
4. Classical TA: S/R zones, trendlines, EMA 20/50/200, RSI + divergence, MACD, ADX regime, Bollinger,
   candlestick confirmation, Fibonacci retracements (0.5-0.786 OTE) and extensions for targets, pivots.
5. Wyckoff / volume logic: accumulation vs distribution, springs and upthrusts when visible.
6. Fundamentals & intermarket: central-bank policy (Fed/ECB/BoJ/BoE), CPI, NFP, PMI, yields, DXY,
   risk sentiment, geopolitics, crypto flows (ETFs, regulation). Weigh the headlines you are given by
   recency and impact. Never invent news that is not in the input.
7. Event risk: if a HIGH impact event for the instrument's currencies is within ~60 minutes,
   prefer NO_TRADE or a pending order placed after the event.
8. Risk management: stop loss beyond the structure that invalidates the idea plus an ATR buffer,
   never a random fixed number. Minimum reward:risk 1.5 to TP1. Three targets: TP1 (nearest
   liquidity/level, ~1.5R), TP2 (next major level, ~2.5R), TP3 (extension / HTF level).
9. Be honest: if confluence is weak or signals conflict, the correct answer is NO_TRADE.
   Confidence above 75 requires HTF + LTF + fundamentals aligned.

OUTPUT: respond with ONLY one JSON object, no markdown, matching exactly this shape:
{
  "decision": "LONG" | "SHORT" | "NO_TRADE",
  "confidence": 0-100,
  "order_type": "MARKET" | "BUY_LIMIT" | "SELL_LIMIT" | "BUY_STOP" | "SELL_STOP" | "NONE",
  "entry": number, "stop_loss": number, "tp1": number, "tp2": number, "tp3": number,
  "holding_horizon": "string, e.g. 'intraday 4-12h'",
  "summary": "2-3 sentence executive summary",
  "technical_view": "paragraph",
  "fundamental_view": "paragraph referencing the specific headlines/events used",
  "key_levels": [{"price": number, "label": "string"}],
  "scenarios": [
    {"name": "string", "probability": 0-100, "path": [number, number, number],
     "trigger": "what confirms this scenario", "description": "string"}
  ],
  "invalidation": "what price action kills the idea",
  "risks": ["string"],
  "checklist": [{"item": "string", "passed": true|false}]
}
Scenarios: give 2-3 (bullish / bearish / range), probabilities summing to ~100, each path = 3 future
price waypoints in order. For NO_TRADE still fill entry/SL/TPs with the best conditional setup
(the level you would wait for) and set order_type to a pending type or NONE."""


SCALPER_PROMPT = """You are a professional intraday scalper on a prop desk, trading 5- and 15-minute charts
on gold, FX majors, indices and crypto CFDs. You are paid to be selective: most of the day you wait.

HOW YOU READ THE MARKET
- Bias comes from M15/H1 structure; execution is on M5. Never fight a strong higher-timeframe trend
  unless there is a clear liquidity sweep followed by an M5 change of character (CHoCH).
- Liquidity first: where are the stops? Previous-day high/low, Asian range high/low, equal highs/lows,
  round numbers. The best scalps come right after those pools are swept and price snaps back.
- VWAP is the intraday fair price. In a trend, buy/sell pullbacks to VWAP; at +/-2 sigma expect mean reversion.
- Timing: London open and New York open killzones give follow-through. Asia and late NY are slow:
  smaller targets or no trade. Never open a scalp within 30 minutes of a high-impact release.
- Confirmation on M5: displacement candle, BOS/CHoCH, fair value gap left behind, rejection wick.
- Cost matters: if the spread is more than ~15% of the stop distance, the trade is not worth it.
- Evidence beats opinion: each setup line may carry its walk-forward backtest result on this market.
  A setup that loses in backtest is not tradeable no matter how good it looks today. Only A / A+
  setups are traded; B and C mean WAIT. Never upgrade a grade the engine capped.
- Use the intermarket line (DXY / yields) and how much of the average daily range is used:
  continuation trades late in an exhausted range are weak.
- Read the macro board (DXY, US10Y, VIX, S&P 500, oil, silver) for the risk mood: gold and yen tend to
  benefit from risk-off, equities/crypto from risk-on. Volume profile POC / VAH / VAL are magnets and
  reaction levels intraday; Trump / tariff headlines can move everything within minutes.

YOUR TASK
You get the engine's measured context and a list of detected setups with grades. Pick the single best
setup, refine its levels if structure justifies it, or reject everything with NO_TRADE. Explain in
plain trader language the exact trigger, why it works now, and what would make you exit early.
Stops go beyond the level that invalidates the idea (sweep wick, broken level, VWAP band) plus a buffer.
TP1 >= 1.2R at the nearest liquidity, TP2 the next pool (>= 2R preferred), TP3 a runner. A scalp lives
15-90 minutes; give a validity window. Never invent news or prices that are not in the input.

OUTPUT: respond with ONLY one JSON object, no markdown, exactly this shape:
{
  "decision": "LONG" | "SHORT" | "NO_TRADE",
  "confidence": 0-100,
  "setup": "name of the setup you chose (or the one you are waiting for)",
  "grade": "A+" | "A" | "B" | "C",
  "order_type": "MARKET" | "BUY_LIMIT" | "SELL_LIMIT" | "BUY_STOP" | "SELL_STOP" | "NONE",
  "entry": number, "stop_loss": number, "tp1": number, "tp2": number, "tp3": number,
  "trigger": "exact condition to enter, e.g. 'M5 close back above 4093 after the sweep'",
  "valid_minutes": number,
  "management": "how to manage: partials, break-even, trailing, early exit",
  "summary": "2 sentences a trader can read in 5 seconds",
  "technical_view": "short paragraph: structure, liquidity, VWAP, session",
  "fundamental_view": "short paragraph on the headlines/events that matter right now",
  "scenarios": [
    {"name": "string", "probability": 0-100, "path": [number, number, number],
     "trigger": "what confirms it", "description": "string"}
  ],
  "invalidation": "price action that kills the idea",
  "risks": ["string"]
}
Give 2-3 scenarios whose probabilities sum to ~100; each path is 3 price waypoints over the next 1-2 hours.
BREVITY: keep every text field to at most 2 short sentences and each scenario description to 1 sentence. Think efficiently.
For NO_TRADE, still fill the levels with the setup you would wait for and set order_type to a pending type or NONE."""


PLAN_PROMPT = """You are a professional trading coach. The trader follows a TESTED rule-based plan (their own
TradingView strategy with a Chandelier trailing-stop exit). The plan's state (waiting / new signal / in a trade) is
given to you and it decides. Your job:
- Explain the current state in plain, friendly words a retail trader understands in 10 seconds.
- Describe the market structure and context (trend, key levels, VWAP, liquidity) that supports or threatens the plan.
- Check the news, calendar and macro board: if a high-impact release is within ~60 minutes or a headline clearly
  threatens the trade, say so and set decision to NO_TRADE as a caution; otherwise mirror the plan's state
  (LONG / SHORT if a signal or open trade exists, NO_TRADE while waiting).
- Never invent prices or news. Never promise outcomes.

OUTPUT: respond with ONLY one JSON object with the same keys as always:
decision, confidence, setup, grade, order_type, entry, stop_loss, tp1, tp2, tp3, trigger, valid_minutes, management,
summary, technical_view, fundamental_view, scenarios (2-3 with name, probability, path, trigger, description),
invalidation, risks. Use the plan's entry and stop if a trade exists; otherwise use the current price and a 1-ATR stop.
BREVITY: every text field at most 2 short sentences."""


def lang_rule(lang: str) -> str:
    """Instruction to write the human-readable fields in the user's language."""
    from i18n import AI_LANGUAGE
    if lang == "en" or lang not in AI_LANGUAGE:
        return ""
    return ("\n\nLANGUAGE: write every human-readable text value (summary, trigger, management, technical_view, "
            f"fundamental_view, invalidation, risks, scenario name/trigger/description) in {AI_LANGUAGE[lang]}, "
            "in plain words a retail trader understands. Keep JSON keys, the decision / grade / order_type values, "
            "the setup name, numbers and tickers (XAUUSD, VWAP, ATR, DXY) exactly in English."
            + (" Never use Chinese characters anywhere; write Mongolian only in Cyrillic letters." if lang == "mn" else ""))


CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")
TEXT_FIELDS = ("summary", "trigger", "management", "technical_view", "fundamental_view", "invalidation")


def fix_language(sig: Dict, lang: str, client, model: str) -> Dict:
    """DeepSeek sometimes slips Chinese into Mongolian/English answers: rewrite only the affected fields."""
    if lang == "zh":
        return sig
    bad = {k: sig[k] for k in TEXT_FIELDS if isinstance(sig.get(k), str) and CJK.search(sig[k])}
    if isinstance(sig.get("risks"), list) and any(CJK.search(str(x)) for x in sig["risks"]):
        bad["risks"] = sig["risks"]
    for i, sc in enumerate(sig.get("scenarios") or []):
        for f in ("name", "trigger", "description"):
            if isinstance(sc, dict) and CJK.search(str(sc.get(f, ""))):
                bad[f"scenario{i}_{f}"] = sc[f]
    if not bad:
        return sig
    from i18n import AI_LANGUAGE
    target = AI_LANGUAGE.get(lang, "English")
    try:
        r = client.chat.completions.create(
            model=model, temperature=0, max_tokens=6000,
            messages=[{"role": "system", "content": f"Translate every value of this JSON object into {target}. "
                                                    "Output the same keys, JSON only, no Chinese characters at all."},
                      {"role": "user", "content": json.dumps(bad, ensure_ascii=False)}])
        fixed = _extract_json_any(r.choices[0].message.content or "")
    except Exception:  # noqa: BLE001 - keep the original rather than fail the whole signal
        return sig
    for k, v in fixed.items():
        if k.startswith("scenario") and "_" in k:
            idx, f = k[len("scenario"):].split("_", 1)
            try:
                sig["scenarios"][int(idx)][f] = v
            except (IndexError, ValueError, TypeError, KeyError):
                pass
        elif k in bad:
            sig[k] = v
    return sig


def _extract_json_any(text: str) -> Dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a:b + 1]) if a != -1 and b != -1 else {}


def provider_key(provider: str) -> Optional[str]:
    return os.getenv(AI_PROVIDERS[provider]["key_env"])


def rule_based_signal(symbol: str, analyses: List[TFAnalysis]) -> Dict:
    """Deterministic fallback signal from the confluence score (works without any AI key)."""
    inst = INSTRUMENTS[symbol]
    ltf = analyses[0]
    score = mtf_score(analyses)
    htf_agree = all(a.score * score > 0 for a in analyses)
    price, a = ltf.price, ltf.atr
    if abs(score) < 25 or not htf_agree:
        decision = "NO_TRADE"
    else:
        decision = "LONG" if score > 0 else "SHORT"
    side = 1 if (decision == "LONG" or (decision == "NO_TRADE" and score >= 0)) else -1
    if side == 1:
        struct = ltf.supports[0]["price"] if ltf.supports else price - 1.5 * a
        sl = min(struct - 0.5 * a, price - 1.0 * a)
    else:
        struct = ltf.resistances[0]["price"] if ltf.resistances else price + 1.5 * a
        sl = max(struct + 0.5 * a, price + 1.0 * a)
    r = abs(price - sl)
    tps = [price + side * m * r for m in (1.5, 2.5, 4.0)]
    rnd = lambda x: round(float(x), inst.digits)
    return {
        "decision": decision,
        "confidence": int(min(90, abs(score) * (1.0 if htf_agree else 0.6))),
        "order_type": "MARKET" if decision != "NO_TRADE" else "NONE",
        "entry": rnd(price), "stop_loss": rnd(sl), "tp1": rnd(tps[0]), "tp2": rnd(tps[1]), "tp3": rnd(tps[2]),
        "holding_horizon": "per chosen timeframe",
        "summary": f"Rule engine: MTF confluence score {score:+.0f} "
                   f"({'all timeframes aligned' if htf_agree else 'timeframes conflict'}).",
        "technical_view": "; ".join(f"{x.tf}: {x.trend}, {x.structure}, score {x.score:+.0f}" for x in analyses),
        "fundamental_view": "Not evaluated by the rule engine - enable an AI provider for news analysis.",
        "key_levels": [{"price": rnd(z["price"]), "label": f"S {ltf.tf}"} for z in ltf.supports[:2]] +
                      [{"price": rnd(z["price"]), "label": f"R {ltf.tf}"} for z in ltf.resistances[:2]],
        "scenarios": [
            {"name": "Trend continuation", "probability": 55, "path": [rnd(price + side * 0.7 * r), rnd(tps[0]), rnd(tps[1])],
             "trigger": "hold above/below entry", "description": "Momentum follows the confluence bias."},
            {"name": "Reversal", "probability": 45, "path": [rnd(price - side * 0.5 * r), rnd(sl), rnd(sl - side * r)],
             "trigger": "close beyond stop structure", "description": "Bias fails and price sweeps the stop."},
        ],
        "invalidation": f"Close beyond {rnd(sl)}",
        "risks": ["No news/fundamental filter applied"],
        "checklist": [{"item": "HTF and LTF aligned", "passed": htf_agree},
                      {"item": "|score| >= 25", "passed": abs(score) >= 25}],
        "engine": "rule-based",
    }


def scalp_rule_signal(ctx, setups) -> Dict:
    """Deterministic scalp signal: best detected setup if it grades B or better, else wait."""
    from scalping import setup_to_signal

    d = ctx.inst.digits
    if not setups:
        return {"decision": "NO_TRADE", "confidence": 20, "setup": "None - wait", "grade": "-",
                "order_type": "NONE", "entry": round(ctx.price, d), "stop_loss": round(ctx.price - ctx.atr, d),
                "tp1": round(ctx.price + ctx.atr, d), "tp2": round(ctx.price + 2 * ctx.atr, d),
                "tp3": round(ctx.price + 3 * ctx.atr, d),
                "summary": "No clean setup on M5 right now. Patience is a position.",
                "trigger": "Wait for a sweep of a key level or a VWAP retest in trend direction.",
                "engine": "rule-based scalper", "scenarios": []}
    best = setups[0]
    tradeable = best.grade in ("A+", "A")
    sig = setup_to_signal(best, ctx, None if tradeable else "NO_TRADE")
    risk = abs(best.entry - best.stop)
    mid = lambda a, b: round((a + b) / 2, d)
    sig.update(
        summary=(f"{best.grade} {best.side.lower()} - {best.name}. " if tradeable else
                 f"Best idea is only grade {best.grade} (needs A or A+); wait. ") + best.trigger,
        technical_view="; ".join(best.reasons),
        fundamental_view="Rule engine does not read headlines - check the news panel or enable an AI provider.",
        invalidation=f"M5 close beyond {best.stop}",
        risks=[r for r in best.reasons if "against" in r or "slow" in r or "spread" in r or "news" in r],
        engine="rule-based scalper",
        scenarios=[
            {"name": "Setup plays out", "probability": 50 + 5 * max(0, best.points - 2),
             "path": [mid(best.entry, best.tp1), best.tp1, best.tp2],
             "trigger": best.trigger, "description": "Liquidity target reached."},
            {"name": "Stopped out", "probability": 50 - 5 * max(0, best.points - 2),
             "path": [round(best.entry - best.direction * 0.5 * risk, d), best.stop,
                      round(best.stop - best.direction * 0.5 * risk, d)],
             "trigger": f"close beyond {best.stop}", "description": "Idea invalidated; price continues the other way."},
        ],
    )
    return sig


LEVEL_KEYS = ("entry", "stop_loss", "tp1", "tp2", "tp3")

# Enforced on providers that support structured output (Ollama, Gemini); small models drift without it.
_STR, _NUM = {"type": "string"}, {"type": "number"}
SIGNAL_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["LONG", "SHORT", "NO_TRADE"]},
        "confidence": _NUM, "setup": _STR, "grade": {"type": "string", "enum": ["A+", "A", "B", "C"]},
        "order_type": {"type": "string", "enum": ["MARKET", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "NONE"]},
        "entry": _NUM, "stop_loss": _NUM, "tp1": _NUM, "tp2": _NUM, "tp3": _NUM,
        "trigger": _STR, "valid_minutes": _NUM, "management": _STR, "summary": _STR,
        "technical_view": _STR, "fundamental_view": _STR, "invalidation": _STR,
        "risks": {"type": "array", "items": _STR},
        "scenarios": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": _STR, "probability": _NUM, "path": {"type": "array", "items": _NUM},
                           "trigger": _STR, "description": _STR},
            "required": ["name", "probability", "path", "trigger", "description"]}},
    },
    "required": ["decision", "confidence", "setup", "grade", "order_type", "entry", "stop_loss", "tp1", "tp2",
                 "tp3", "trigger", "valid_minutes", "management", "summary", "technical_view",
                 "fundamental_view", "invalidation", "risks", "scenarios"],
}


def as_list(v) -> list:
    """The model sometimes sends a list field as one string: split it into items instead of letters."""
    if isinstance(v, str):
        return [x.strip(" -•\t") for x in re.split(r"[\r\n;]+", v) if x.strip(" -•\t")]
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else []


def merge_signals(ai: Dict, base: Dict, price: float, atr_val: float) -> Dict:
    """Lay the AI's answer over the engine's signal; keep engine levels if the AI's are unusable."""
    ai = dict(ai)
    side = str(ai.get("decision", "")).upper()
    ai["decision"] = {"BUY": "LONG", "LONG": "LONG", "SELL": "SHORT", "SHORT": "SHORT"}.get(side, "NO_TRADE")
    if ai.get("grade") not in ("A+", "A", "B", "C"):
        ai.pop("grade", None)
    ai["scenarios"] = [x for x in ai.get("scenarios") or [] if isinstance(x, dict)]
    ai["risks"] = as_list(ai.get("risks"))
    try:
        far = abs(float(ai.get("entry")) - price) > 5 * atr_val
    except (TypeError, ValueError):
        far = False
    if far:
        # prices that don't belong to this market = the model answered about something else; drop it all
        out = dict(base)
        out["warnings"] = ["AI answer did not match this market (prices far from current) - ignored, engine signal shown."]
        out["engine"] = f"{base.get('engine')} (AI ignored)"
        return out
    out = dict(base)
    for k, v in ai.items():
        if v not in (None, "", [], {}):
            out[k] = v
    bad = [w for w in validate_signal(out, price, atr_val)
           if "geometry" in w or "non-numeric" in w or "ATR from current price" in w]
    if bad:
        for k in LEVEL_KEYS + ("order_type",):
            out[k] = base.get(k)
        if out.get("decision") in ("LONG", "SHORT") and base.get("decision") != out["decision"]:
            out["decision"] = "NO_TRADE"
        out["warnings"] = [f"AI levels rejected ({bad[0]}) - engine levels shown."]
    else:
        out["warnings"] = validate_signal(out, price, atr_val)
    try:
        out["valid_minutes"] = int(min(120, max(15, float(out.get("valid_minutes") or 45))))
    except (TypeError, ValueError):
        out["valid_minutes"] = 45
    if out.get("grade") in ("B", "C") and out.get("decision") in ("LONG", "SHORT"):
        out["decision"] = "NO_TRADE"
        out["warnings"].append(f"Grade {out['grade']} idea - shown as WAIT. Only A / A+ setups are traded.")
    out["engine"] = ai.get("engine", base.get("engine"))
    return out


def _extract_json(text: str) -> Dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # reasoning models (DeepSeek R1, Qwen3)
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("model did not return JSON")
    data = json.loads(text[start:end + 1])
    # small models sometimes wrap the answer: {"trade": {...}} or {"signal": {...}}
    if "decision" not in data:
        for v in data.values():
            if isinstance(v, dict) and "decision" in v:
                return v
        raise ValueError("JSON has no decision field")
    return data


def validate_signal(sig: Dict, price: float, atr_val: float) -> List[str]:
    """Sanity-check the AI's numbers; returns a list of warnings."""
    warn = []
    d, e, sl = sig.get("decision"), sig.get("entry"), sig.get("stop_loss")
    tps = [sig.get(k) for k in ("tp1", "tp2", "tp3")]
    try:
        e, sl = float(e), float(sl)
        tps = [float(t) for t in tps]
    except (TypeError, ValueError):
        return ["Signal has missing or non-numeric prices."]
    if d == "LONG" and not (sl < e < tps[0]):
        warn.append("LONG geometry is wrong (need SL < entry < TP1).")
    if d == "SHORT" and not (sl > e > tps[0]):
        warn.append("SHORT geometry is wrong (need SL > entry > TP1).")
    if abs(e - price) > 5 * atr_val:
        warn.append(f"Entry is {abs(e - price) / atr_val:.1f} ATR from current price.")
    risk = abs(e - sl)
    if risk > 0 and d in ("LONG", "SHORT"):
        rr = abs(tps[0] - e) / risk
        if rr < 1.2:
            warn.append(f"Reward:risk to TP1 only {rr:.2f}.")
        if risk < 0.3 * atr_val:
            warn.append("Stop is tighter than 0.3 ATR - likely to be wicked out.")
    return warn


def ai_signal(symbol: str, tf: str, analyses: List[TFAnalysis], news_text: str,
              provider: str, model: str, scalp_text: str = "", scalp_atr: Optional[float] = None,
              lang: str = "en", lessons_text: str = "", plan_mode: bool = False) -> Dict:
    from openai import OpenAI

    cfg = AI_PROVIDERS[provider]
    key = provider_key(provider)
    if not key:
        raise RuntimeError(f"Set {cfg['key_env']} in your .env file to use {provider}.")
    # e.g. DEEPSEEK_BASE_URL for keys bought from a reseller / relay site
    base_url = os.getenv(cfg["key_env"].replace("_API_KEY", "_BASE_URL"))
    client = OpenAI(base_url=base_url or cfg["base_url"], api_key=key, timeout=240, max_retries=2)

    inst = INSTRUMENTS[symbol]
    ltf = analyses[0]
    now = datetime.now(timezone.utc)
    user = f"""Instrument: {symbol} (Pepperstone CFD, contract {inst.contract_size}/lot, pip {inst.pip})
Trading timeframe: {tf}.  Current UTC time: {now:%Y-%m-%d %H:%M} ({now:%A}).
Current price: {ltf.price:.{inst.digits}f}.  Multi-timeframe confluence score: {mtf_score(analyses):+.0f} (-100..+100).

# Technical data (computed from live candles)
{chr(10).join(to_prompt_text(a, inst.digits) for a in analyses)}

{"# Intraday scalping context (measured)" + chr(10) + scalp_text + chr(10) if scalp_text else ""}
{lessons_text + chr(10) if lessons_text else ""}
# News & calendar
{news_text}

Give your professional trade decision as the JSON object described. Use {inst.digits} decimals for prices.{lang_rule(lang)}"""

    system = PLAN_PROMPT if plan_mode else (SCALPER_PROMPT if scalp_text else SYSTEM_PROMPT)
    kwargs = dict(model=model, messages=[{"role": "system", "content": system},
                                         {"role": "user", "content": user}],
                  temperature=0.3, max_tokens=16000)
    if cfg.get("schema"):
        kwargs["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "trade_signal", "schema": SIGNAL_SCHEMA}}
    elif cfg["json_mode"]:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    text = msg.content or ""
    if not text.strip():
        # reasoning models can burn the whole budget thinking and return nothing: retry once with more room
        kwargs["max_tokens"] = 16000
        resp = client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        text = msg.content or ""
    if not text.strip():
        raise RuntimeError("model returned an empty answer (used all tokens thinking)")
    try:
        sig = _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        # one repair attempt: ask the model to reformat its own answer
        fix = client.chat.completions.create(
            model=model, temperature=0, max_tokens=4000,
            messages=[{"role": "system", "content": "Rewrite the trading answer below as ONE JSON object with exactly these keys "
                                                    "(map trade_type->decision, entry_price->entry, take_profit list->tp1/tp2/tp3): "
                                                    + json.dumps(SIGNAL_SCHEMA["required"]) + ". Output JSON only."},
                      {"role": "user", "content": text[-12000:]}])
        sig = _extract_json(fix.choices[0].message.content or "")
    sig = fix_language(sig, lang, client, model)
    sig["engine"] = f"{provider} · {model}"
    reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
    if reasoning:
        sig["model_reasoning"] = reasoning
    sig["warnings"] = validate_signal(sig, ltf.price, scalp_atr or ltf.atr)
    return sig

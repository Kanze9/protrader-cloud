"""ProTrader AI - scalping signal desk.  Run:  run.bat  (or: streamlit run app.py)"""
import os
import time
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

import backtest as bt
import hud
import i18n
from i18n import T, setup_name, tr_dyn
import journal
import lessons as lessons_mod
import json

import meanrev
import notify
import plans
import proplan
import quality
import seasonal
import orb_tool
import timemachine
import zones as zones_mod
import macro
import news as newsmod
from ai_brain import ai_signal, as_list, merge_signals, provider_key, rule_based_signal, scalp_rule_signal
from config import AI_PROVIDER, AI_PROVIDERS, BARS, INSTRUMENTS, MTF_STACK, TIMEFRAMES
from data_feed import live_quote, load_tv_pair, SOURCES, load_intermarket, load_ohlc
from risk import position_size, reward_usd
from scalping import Context, add_vwap, as_dicts, context_text, find_setups, structure_events
from userstrats import PRO_PULLBACK, SIGNAL_V26, htf_features
from technical import add_indicators, analyze_tf, mtf_score, order_blocks, pivots

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
st.set_page_config(page_title="ProTrader AI", page_icon="◆", layout="wide")

UP, DOWN, MUTED, GRID, BG = hud.TEAL, hud.RED, hud.MUTED, "rgba(0,229,255,.07)", "rgba(0,0,0,0)"
st.markdown(hud.CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- data helpers

@st.cache_data(ttl=25, show_spinner=False)
def get_candles(symbol, tf, source):
    df = load_ohlc(symbol, tf, BARS[tf], source)
    return df, df.attrs.get("source", "?")


@st.cache_data(ttl=25, show_spinner=False)
def get_peer(tv_symbol, tf):
    return load_tv_pair(tv_symbol, tf, BARS[tf])


@st.cache_data(ttl=1, show_spinner=False)
def get_quote(symbol, source):
    return live_quote(symbol, source)


def patch_live(df, tf_, q):
    """Put the live price into the forming candle (or start a new one) so the chart moves between full reloads.
    Signals never use this candle: they read closed candles only."""
    if not q or df.empty:
        return df
    df = df.copy()
    step = pd.Timedelta(minutes=TIMEFRAMES[tf_][1])
    last = df.index[-1]
    p = q["price"]
    if q["time"] >= last + step:
        start = last + step * int((q["time"] - last) / step)
        df.loc[start] = [p, p, p, p, 0.0]
    elif q["time"] >= last:
        df.loc[last, "close"] = p
        df.loc[last, "high"] = max(df.loc[last, "high"], p)
        df.loc[last, "low"] = min(df.loc[last, "low"], p)
    return df


@st.cache_data(ttl=25, show_spinner=False)
def get_inter(symbol, tf):
    return load_intermarket(symbol, tf, BARS.get(tf, 600))


@st.cache_data(ttl=60, show_spinner=False)
def get_backtest(symbol, tf):
    return bt.load(symbol, tf)


SETUP_NAMES = ["Liquidity sweep reversal", "VWAP pullback with trend", "BOS break & retest", "CHoCH break & retest",
               "Asian range breakout", "Fair value gap retest", PRO_PULLBACK, SIGNAL_V26]


def closed_only(df, t):
    """Drop the still-forming candle: signals may only change when a candle closes (no repainting)."""
    if len(df) > 2 and df.index[-1] + pd.Timedelta(minutes=TIMEFRAMES[t][1]) > pd.Timestamp.now(tz="UTC"):
        return df.iloc[:-1]
    return df


def extra_features(symbol, tf, source, exec_df):
    """Higher-timeframe values for the user's strategies (Pro Pullback / Signal v26), closed bars only."""
    try:
        frames = {"H4": closed_only(get_candles(symbol, "H4", source)[0], "H4"),
                  "H1": closed_only(get_candles(symbol, "H1", source)[0], "H1"),
                  "M15": exec_df if tf == "M15" else closed_only(get_candles(symbol, "M15", source)[0], "M15")}
        return htf_features(exec_df, TIMEFRAMES[tf][1], frames)
    except Exception:  # noqa: BLE001
        return None


def edge_for(trades, name):
    """Match an engine or AI setup name (AI may reword it) to backtest stats."""
    name = str(name or "").lower()
    for known in SETUP_NAMES:
        words = [w for w in known.lower().split() if len(w) > 3]
        if known.lower() in name or (words and all(w in name for w in words)):
            return bt.edge(trades, known)
    return None


@st.cache_resource(show_spinner=False)
def get_quality():
    return quality.load()


def canonical_setup(name):
    """Short engine name for an engine/AI setup label (AI may write a whole sentence)."""
    low = str(name or "").lower()
    for known in SETUP_NAMES:
        words = [w for w in known.lower().replace("(", "").replace(")", "").split() if len(w) > 3]
        if known.lower() in low or (words and all(w in low for w in words[:3])):
            return known
    return str(name or "")[:40]


def similar_txt(q):
    return T("won {w}% · {r}R (unseen data)", w=f"{q['win']:.0f}", r=f"{q['avg_r']:+.2f}") if q else "—"


def edge_txt(e):
    return T("{w}% win · {r}R · {n} trades", w=f"{e['win']:.0f}", r=f"{e['avg_r']:+.2f}", n=e["n"]) if e else "—"


def side_txt(side):
    return T(str(side))


def order_txt(ot):
    ot = str(ot or "").replace("_", " ")
    return "—" if ot in ("", "NONE") else T(ot)


def session_txt(ctx):
    if ctx.session["killzone"]:
        return T(ctx.session["killzone"])
    return ", ".join(T(x) for x in ctx.session["sessions"])


def quality_txt(q):
    return T(q.split(" (")[0])


@st.cache_data(ttl=300, show_spinner=False)
def get_board():
    return macro.fetch_board()


@st.cache_data(ttl=300, show_spinner=False)
def get_news():
    return newsmod.fetch_news()


@st.cache_data(ttl=900, show_spinner=False)
def get_calendar():
    return newsmod.fetch_calendar()


@st.cache_data(ttl=3600, show_spinner=False)
def get_strategy_stats():
    try:
        with open(os.path.join(os.path.dirname(__file__), "models", "strategy_stats.json"), encoding="utf-8") as fh:
            return json.load(fh)["stats"]
    except (OSError, ValueError, KeyError):
        return {}


STRAT_LABEL = {"pro": "Pro Pullback + trailing stop", "v26": "Signal v26 + trailing stop",
               "mr_d7": "Connors Double-7 dip-buy (high win rate)", "mr_rsi2": "Connors RSI(2) dip-buy (high win rate)",
               "mr_rsi2x": "EURUSD deep dip-buy + news-spike filter (10y tested)",
               "mr_eur": "EURUSD dip-buy / rally-sell + news-spike filter (10y tested)",
               "mr_gold": "Gold deep dip-buy + daily trend + dollar check (10y tested)",
               "v26_t05": "Signal v26 + 0.5R target (high win rate)"}
# High win-rate mode: best tested plan per market and the timeframe it was tested on (see meanrev.py / README)
HIGHWIN = {"XAUUSD": ("mr_d7", "D1"), "EURUSD": ("mr_eur", "H1"), "BTCUSD": ("v26_t05", "H1"), "USDJPY": None}
# dip-buy plans always read their own tested timeframe, so their signals also show on a faster (scalp) chart
MR_TF = {"mr_rsi2": "H1", "mr_rsi2x": "H1", "mr_eur": "H1", "mr_gold": "H1", "mr_bb": "H1", "mr_d7": "D1", "mr_any": "D1"}
# markets where auto mode uses the high win-rate plan (EURUSD: scalp methods all lost after spread in a 2-year test)
AUTO_PREFER = {"EURUSD": "mr_eur", "XAUUSD": "mr_gold"}
PEER = {"mr_eur": "GBPUSD", "mr_gold": "EURUSD"}       # the dollar cross-check pair for each plan


def plan_stats(strat, sym, t):
    st_ = get_strategy_stats()
    t = MR_TF.get(strat, t)
    if f"{strat}|{sym}|{t}" in st_ and (st_[f"{strat}|{sym}|{t}"]["n"] >= 30 or f"{strat}|{sym}|H1" not in st_):
        return st_[f"{strat}|{sym}|{t}"], t            # only trust a timeframe's own stats with 30+ trades
    if f"{strat}|{sym}|H1" in st_:
        return st_[f"{strat}|{sym}|H1"], "H1"
    return None, None


def auto_strategy(sym, t):
    """Best tested strategy for this market (H1 2-year result decides); None if both lose here."""
    if sym in AUTO_PREFER:
        return AUTO_PREFER[sym]
    best, best_r = None, 0.0
    for strat in ("pro", "v26"):
        sh = get_strategy_stats().get(f"{strat}|{sym}|H1")
        if sh and sh["avg_r"] > best_r and sh["n"] >= 30:
            best, best_r = strat, sh["avg_r"]
    return best


def h1_ema200_aligned(sym, t, source_, exec_df):
    from technical import add_indicators as _ai
    e = _ai(closed_only(get_candles(sym, "H1", source_)[0], "H1"))["ema200"]
    e.index = e.index + pd.Timedelta(hours=1)
    tgt = exec_df.index + pd.Timedelta(minutes=TIMEFRAMES[t][1])
    out = e.reindex(e.index.union(tgt)).ffill().reindex(tgt)
    out.index = exec_df.index
    return out


@st.cache_data(ttl=900, show_spinner=False)
def plan_state(sym, t, source_, strat, last_bar):
    """Strategy trades on the loaded (closed) history + the condition checks on the last closed candle."""
    d_raw = closed_only(get_candles(sym, t, source_)[0], t)
    h4 = closed_only(get_candles(sym, "H4", source_)[0], "H4") if t != "H4" else None
    h1e = h1_ema200_aligned(sym, t, source_, d_raw) if strat in ("v26", "v26_t05") and t != "H1" else None
    daily = closed_only(get_candles(sym, "D1", source_)[0], "D1")
    if strat.startswith("mr_"):
        pt = MR_TF.get(strat, t)
        if pt != t:
            d_raw = closed_only(get_candles(sym, pt, source_)[0], pt)
        cfg = meanrev.exit_cfg(sym, strat)
        peer = get_peer(PEER[strat], pt) if strat in PEER else None             # USD-wide cross-check
        peer = closed_only(peer, pt) if peer is not None else None
        trs = meanrev.trades(d_raw, sym, strat, cfg["stop_atr"], tp1_r=cfg["tp1_r"], peer=peer)
        dm = meanrev.prepare(d_raw)
        if peer is not None:
            dm["usd_wide"] = meanrev.usd_wide(dm, peer)
        if strat == "mr_gold":
            meanrev.add_daily_trend(dm)
        # a signal is known when its candle closes: draw it on the chart candle that closes at the same moment
        return {"trades": trs, "checks": {"mr": meanrev.checks(dm, len(dm) - 1, strat), "trend": 0},
                "last_close": float(dm.close.iloc[-1]), "atr": float(dm.atr.iloc[-1]), "last_time": dm.index[-1],
                "shift": pd.Timedelta(minutes=TIMEFRAMES[pt][1] - TIMEFRAMES[t][1]), "plan_tf": pt}
    base_strat = "v26" if strat == "v26_t05" else strat
    trs = proplan.trades(d_raw, sym, TIMEFRAMES[t][1], base_strat, h4=h4, h1_ema200=h1e, daily=daily,
                         target_r=0.5 if strat == "v26_t05" else None)
    d = add_indicators(d_raw)
    chk = proplan.pro_pullback_checks(d, proplan.h4_trend(d_raw, h4, TIMEFRAMES[t][1]), len(d) - 1)
    chk["daily"] = int(proplan.daily_trend(d_raw, daily, TIMEFRAMES[t][1]).iloc[-1])
    chk["not_monday"] = d.index[-1].weekday() != 0
    return {"trades": trs, "checks": chk, "last_close": float(d.close.iloc[-1]), "atr": float(d.atr.iloc[-1]),
            "last_time": d.index[-1]}


def quality_word(g):
    return T({"A+": "Strong", "A": "Strong", "B": "Weak", "C": "No edge"}.get(str(g), "No edge"))


def fmt(x, d):
    return f"{float(x):,.{d}f}"


def build_state(symbol, tf, source):
    """Load all timeframes and compute analysis + scalp context."""
    stack = MTF_STACK[tf]
    frames, src = {}, ""
    for t in stack:
        frames[t], lbl = get_candles(symbol, t, source)
        if t == tf:
            src = lbl
    eng = {t: closed_only(frames[t], t) for t in stack}          # engine sees closed candles only
    analyses = [analyze_tf(eng[t], t) for t in stack]
    scalp = tf in ("M5", "M15")
    ctx = setups = None
    events = newsmod.relevant_events(get_calendar(), symbol)
    news_block = bool(newsmod.upcoming_high_impact(events, 30))
    if scalp:
        daily, _ = get_candles(symbol, "D1", source)
        ex = extra_features(symbol, tf, source, eng[tf])
        ctx = Context(eng[tf], symbol, mtf_score(analyses[1:]) if len(analyses) > 1 else analyses[0].score,
                      daily=daily, intermarket=get_inter(symbol, tf),
                      extra=ex.iloc[-1].to_dict() if ex is not None and len(ex) else None)
        setups = find_setups(ctx, news_block)
        trades, _ = get_backtest(symbol, tf)
        setups = bt.apply_edge(setups, trades, hour=pd.Timestamp.now(tz="UTC").hour)
        qb = get_quality()
        for x in setups:
            x.quality = quality.similar(qb, quality.features(ctx, x, symbol)) if qb else None
            if x.quality and x.quality["avg_r"] <= -0.10 and x.grade in ("A+", "A"):
                x.grade = "B"
                x.reasons.append(f"similar past setups lost on unseen data ({x.quality['avg_r']:+.2f}R) - capped at B")
    return {"frames": frames, "src": src, "analyses": analyses, "scalp": scalp, "ctx": ctx,
            "setups": setups or [], "events": events}


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.markdown("### ◆ PROTRADER AI")
    lang_name = st.segmented_control("🌐", list(i18n.LANGS), default="English", key="lang") or "English"
    i18n.set_lang(i18n.LANGS[lang_name])
    simple = st.toggle(T("Simple view"), value=True, help=T("Only the most profitable signal and its reasons. Turn off for the full terminal."))
    symbol = st.selectbox(T("Instrument"), list(INSTRUMENTS), index=list(INSTRUMENTS).index("EURUSD"))
    tf = st.segmented_control(T("Timeframe"), list(TIMEFRAMES), default="M15") or "M15"
    lot_size = st.number_input(T("Lots (size 100000)"), 0.0, 100.0, 0.0, step=0.01, format="%.2f",
                               help=T("Your trade size, like the TradingView order panel. 0 = let the app size it from your balance and risk %."))
    _inst = INSTRUMENTS[symbol]
    if not lot_size:
        st.caption(T("Lot size: auto from balance and risk %"))
    elif _inst.quote_ccy == "USD":
        st.caption(T("Pip value: {v} USD", v=f"{lot_size * _inst.pip * _inst.contract_size:,.2f}"))
    else:
        st.caption(T("Pip value shown in the signal panel"))
    LAYERS = ["Strength zones", "EMA 20/50", "EMA 200", "VWAP", "Bollinger Bands", "Fibonacci", "Order blocks", "FVG & sweeps",
              "Key levels", "Market structure"]
    layers = st.multiselect(T("Chart indicators"), LAYERS, default=["Strength zones", "EMA 20/50", "VWAP", "Key levels",
                                                                     "Market structure"], format_func=T)
    lower_panel = st.segmented_control(T("Lower panel"), ["RSI", "Volume", "MACD"], default="RSI") or "RSI"
    show_struct = "Market structure" in layers
    st.caption(T("M15 = recommended scalping (backtested best) · M5 = fast scalping · H1+ = swing"))
    run = st.button(T("Analyze"), type="primary", use_container_width=True)
    live = st.toggle(T("Live chart"), value=False,
                     help=T("Updates price, chart and setups. Does not call the AI again."))
    live_every = st.select_slider(T("Update every (seconds)"), [2, 3, 5, 10, 30], value=3, disabled=not live,
                                  help=T("Price and the forming candle update this often. Full candle history reloads every 25 s. "
                                         "For true tick-by-tick prices choose the MT5 source (Pepperstone MT5 terminal)."))
    sound = st.toggle(T("Alerts: sound + desktop popup"), value=True,
                      help=T("Needs 'Live chart refresh' on and this tab open (it can be in the background)."))
    alert_vol = st.slider(T("Alert volume"), 1, 10, 8, disabled=not sound)
    test_alert = st.button(T("🔔 Test alert / allow notifications"), use_container_width=True)
    if notify.email_ready():
        st.caption(T("📧 Gmail alerts ready. Start run_alerts.bat to get emails even with this page closed."))
        test_mail = st.button(T("📧 Send test email"), use_container_width=True)
    else:
        st.caption(T("📧 Gmail alerts: not set up yet - run set_email.py (needs a Gmail App Password)."))
        test_mail = False
    alert_txt = st.text_input(T("Price alerts"), placeholder=T("e.g. 4100, 4075.5"),
                              help=T("Comma-separated prices. With live refresh on you get a toast + beep when price crosses one."))

    with st.expander(T("AI brain"), expanded=False):
        use_ai = st.toggle(T("Use AI (DeepSeek)"), value=True)
        provider = AI_PROVIDER
        model = st.selectbox(T("Model"), AI_PROVIDERS[provider]["models"],
                             index=AI_PROVIDERS[provider]["models"].index("deepseek-reasoner"),
                             help=T("reasoner = deeper thinking (default, ~100 s) · chat = faster (~40 s)"))
        if not provider_key(provider):
            st.caption(T("No DeepSeek key in `.env` - run set_key.py. Rule engine is used meanwhile."))
    with st.expander(T("Account & risk"), expanded=False):
        balance = st.number_input(T("Balance (USD)"), 20.0, 10_000_000.0, 50.0, step=10.0,
                                  help=T("Minimum 20 USD. Small accounts are limited by the 0.01 minimum lot."))
        risk_pct = st.slider(T("Risk per trade %"), 0.25, 3.0, 0.5, 0.25)
        leverage = st.number_input(T("Leverage 1:"), 1, 1000, INSTRUMENTS[symbol].default_leverage, step=50)
        use_guard = st.toggle(T("**Risk guard** (prop-firm style)"), value=False,
                              help=T("Optional: stop new signals after a daily loss limit or a number of trades."))
        day_loss_limit = st.slider(T("Daily loss limit %"), 1.0, 10.0, 5.0, 0.5, disabled=not use_guard)
        max_trades = st.number_input(T("Max trades per day"), 1, 50, 10, disabled=not use_guard)
    with st.expander(T("Data"), expanded=False):
        source = st.selectbox(T("Source"), SOURCES, index=0)
    st.caption(T("Testing / education only. Not financial advice."))

if test_mail:
    try:
        import alert_worker
        _res = plans.run_plan(plans.PLANS[0], alert_worker.make_getter())
        _subj, _txt, _html = alert_worker.entry_mail(_res, _res["trades"][-1])
        notify.send_email("[TEST] " + _subj, "Test with the latest signal.\n\n" + _txt, _html)
        st.sidebar.success(T("Test email sent - check your Gmail (and the Spam folder)."))
    except Exception as e:  # noqa: BLE001
        st.sidebar.error(T("Email failed: {e}", e=str(e)[:200]))

if test_alert:
    components.html("""<script>
      const P = window.parent;
      try { if ("Notification" in P && P.Notification.permission === "default") P.Notification.requestPermission(); } catch (e) {}
    </script>""", height=0)

inst = INSTRUMENTS[symbol]
D = inst.digits
# one mode: the best tested plan for each market (EURUSD: dip-buy / rally-sell, 10 years tested)
STRAT = auto_strategy(symbol, tf)
PLAN_MODE = True
key = f"{symbol}-{tf}"

# ---------------------------------------------------------------- risk guard (from the journal)

def risk_guard():
    """Today's (UTC) logged trades and approximate P/L % from their R results (only when the user enables it)."""
    if not use_guard:
        return {"trades": 0, "pnl_pct": 0.0, "blocked": False, "why": ""}
    jdf = journal.load()
    if jdf.empty:
        return {"trades": 0, "pnl_pct": 0.0, "blocked": False, "why": ""}
    today = jdf[jdf["time"].dt.date == pd.Timestamp.now(tz="UTC").date()]
    for idx, row in today.iterrows():                  # settle today's open trades before judging
        if pd.isna(row.get("r_multiple")):
            try:
                candles, _ = get_candles(row["symbol"], "M5", source)
                jdf.loc[idx, ["outcome", "r_multiple"]] = journal.evaluate(row, candles)
            except Exception:  # noqa: BLE001
                pass
    journal.save(jdf)
    today = jdf.loc[today.index]
    pnl_pct = float(pd.to_numeric(today["r_multiple"], errors="coerce").fillna(0).sum()) * risk_pct
    n = len(today)
    why = ""
    if pnl_pct <= -day_loss_limit:
        why = T("daily loss limit hit ({p}% today, limit -{l}%)", p=f"{pnl_pct:+.1f}", l=day_loss_limit)
    elif n >= max_trades:
        why = T("max {n} trades per day reached", n=max_trades)
    return {"trades": n, "pnl_pct": pnl_pct, "blocked": bool(why), "why": why}


guard = risk_guard()


@st.cache_data(ttl=86400, show_spinner=False)
def get_seasonal(symbol):
    return seasonal.stats(symbol)


def current_lessons():
    trades, _ = get_backtest(symbol, tf)
    out = lessons_mod.build(trades, journal.load(), symbol, tf)
    season = seasonal.text(symbol, get_seasonal(symbol))
    if season:
        out.append(season)
    if symbol in ("XAUUSD", "EURUSD", "GBPUSD"):
        out.append("DXY link (tested 2007-2026): moves opposite on the same day ~2/3 of the time, but DXY today does NOT "
                   "predict tomorrow - use it as confirmation, never as a forecast.")
    return out

# ---------------------------------------------------------------- chart

@st.cache_data(ttl=900, show_spinner=False)
def signal_history(symbol, tf, source, last_bar):
    """Engine signals over the visible candles, replayed bar by bar without look-ahead, with real outcomes."""
    df = closed_only(get_candles(symbol, tf, source)[0], tf)
    daily, _ = get_candles(symbol, "D1", source)
    horizon = 12 if tf == "M15" else 36
    hist = df.tail(400 + 140)
    tr = bt.run_backtest(hist, symbol, TIMEFRAMES[tf][1], daily=daily, inter=get_inter(symbol, tf),
                         window=400, step=1, horizon=horizon, extra_df=extra_features(symbol, tf, source, hist))
    if tr.empty:
        return tr
    cache, _ = get_backtest(symbol, tf)
    tr["final_grade"] = [bt.cap_grade(g, bt.evidence_cap(bt.edge(cache, name))[0])
                         for g, name in zip(tr["grade"], tr["setup"])]
    tr["open"] = tr["time"] > df.index[-1] - pd.Timedelta(minutes=TIMEFRAMES[tf][1]) * horizon
    return tr


KEY_LEVELS = ("PDH", "PDL", "Asia high", "Asia low", "POC", "VAH", "VAL")


def badge(fig, y, text, bg, fg="#04070d", yref="y"):
    """Price tag on the right axis, like TradingView."""
    fig.add_annotation(xref="paper", x=1.0, yref=yref, y=y, text=f"<b>{text}</b>", showarrow=False, xanchor="left",
                       bgcolor=bg, bordercolor=bg, borderpad=3, font=dict(size=11, color=fg, family="JetBrains Mono"))


FIB_LEVELS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)


def add_fibonacci(fig, initial, right):
    """Fibonacci retracement of the biggest swing in the visible window (the high and low of the last candles shown)."""
    hi_t, lo_t = initial.high.idxmax(), initial.low.idxmin()
    hi_v, lo_v = float(initial.high.max()), float(initial.low.min())
    up = lo_t < hi_t                                   # low came first: an up-swing, retracements count down from the high
    x0 = min(hi_t, lo_t)
    for r in FIB_LEVELS:
        lvl = hi_v - (hi_v - lo_v) * r if up else lo_v + (hi_v - lo_v) * r
        key = r in (0.5, 0.618)
        fig.add_shape(type="line", x0=x0, x1=right, y0=lvl, y1=lvl, row=1, col=1,
                      line=dict(color="rgba(255,215,0,.75)" if key else "rgba(255,215,0,.35)", width=1.2 if key else 1, dash="dot"))
        fig.add_annotation(x=right, y=lvl, text=f"Fib {r * 100:.1f}% {fmt(lvl, D)}", showarrow=False, xanchor="right",
                           yanchor="bottom", font=dict(size=9, color="rgba(255,215,0,.9)"), row=1, col=1)


def make_chart(S, sig):
    df = S["frames"][tf]
    ctx = S["ctx"]
    base = add_vwap(add_indicators(df)) if ctx is not None else add_indicators(df)   # includes the live candle
    view = base                                   # whole loaded history: pan left to see it
    initial = base.tail(130 if S["scalp"] else 160)
    step = view.index[-1] - view.index[-2]
    right = view.index[-1] + step * 14
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.025)
    fig.add_trace(go.Candlestick(x=view.index, open=view.open, high=view.high, low=view.low, close=view.close,
                                 increasing=dict(line=dict(color=UP, width=1), fillcolor="rgba(0,229,192,.85)"),
                                 decreasing=dict(line=dict(color=DOWN, width=1), fillcolor="rgba(255,77,109,.85)"),
                                 name=symbol, showlegend=False), row=1, col=1)
    lo, hi = initial.low.min(), initial.high.max()
    pad = (hi - lo) * 0.08
    if "EMA 20/50" in layers:
        fig.add_trace(go.Scatter(x=view.index, y=view.ema20, name="EMA 20", line=dict(color="#4dd8ff", width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=view.index, y=view.ema50, name="EMA 50", line=dict(color="#a78bfa", width=1.2)), row=1, col=1)
    if "EMA 200" in layers:
        fig.add_trace(go.Scatter(x=view.index, y=view.ema200, name="EMA 200", line=dict(color="#f0f6fc", width=1.4)), row=1, col=1)
    if "Bollinger Bands" in layers:
        for col_, nm in (("bb_up", "BB upper"), ("bb_mid", "BB mid"), ("bb_lo", "BB lower")):
            fig.add_trace(go.Scatter(x=view.index, y=view[col_], name=nm, showlegend=nm == "BB mid",
                                     line=dict(color="rgba(255,181,71,.55)", width=1, dash="dot" if nm == "BB mid" else "solid")),
                          row=1, col=1)
    if "Fibonacci" in layers:
        add_fibonacci(fig, initial, right)
    if "Strength zones" in layers:
        zres = zones_mod.find_zones(closed_only(df, tf))
        for side_z, col_z in (("buy", "0,229,192"), ("sell", "255,77,109")):
            zz = zres[side_z]
            if not zz:
                continue
            fig.add_shape(type="rect", x0=max(zz["first_time"], view.index[0]), x1=right, y0=zz["bottom"], y1=zz["top"], row=1, col=1,
                          fillcolor=f"rgba({col_z},.16)", line=dict(color=f"rgba({col_z},.8)", width=1.2), layer="below")
            fig.add_annotation(x=right, y=zz["top"] if side_z == "sell" else zz["bottom"], xanchor="right",
                               yanchor="bottom" if side_z == "sell" else "top", showarrow=False, row=1, col=1,
                               text=f"{T('SELL ZONE') if side_z == 'sell' else T('BUY ZONE')} {zz['score']} · {T(zz['label'])} · "
                                    f"{zz['reactions']} {T('reactions')}",
                               bgcolor="rgba(10,22,38,.9)", bordercolor=f"rgb({col_z})", borderpad=3,
                               font=dict(size=10, color=f"rgb({col_z})"))
            lo, hi = min(lo, zz["bottom"]), max(hi, zz["top"])
    if ctx is not None:
        if "VWAP" in layers:
            fig.add_trace(go.Scatter(x=view.index, y=view.vwap, name="VWAP", line=dict(color=hud.AMBER, width=1.4, dash="dot")),
                          row=1, col=1)
        for name, lvl in ctx.levels.items() if "Key levels" in layers else []:
            if name in KEY_LEVELS and lo - pad <= lvl <= hi + pad:
                fig.add_hline(y=lvl, line=dict(color="rgba(0,229,255,.20)", width=1, dash="dot"), row=1, col=1,
                              annotation_text=name, annotation_position="top left", annotation_font=dict(size=9, color=MUTED))
        for g in ctx.fvgs if "FVG & sweeps" in layers else []:
            if g["time"] >= view.index[0]:
                c = "0,229,192" if g["type"] == "bullish" else "255,77,109"
                fig.add_shape(type="rect", x0=g["time"], x1=right, y0=g["bottom"], y1=g["top"], row=1, col=1,
                              fillcolor=f"rgba({c},.08)", line=dict(width=0))
                fig.add_annotation(x=g["time"], y=g["top"], text="FVG", showarrow=False, xanchor="left", yanchor="bottom",
                                   font=dict(size=9, color=f"rgb({c})"), row=1, col=1)
        for w in ctx.sweeps[-3:] if "FVG & sweeps" in layers else []:
            if w["time"] >= view.index[0]:
                fig.add_trace(go.Scatter(x=[w["time"]], y=[w["extreme"]], mode="markers", showlegend=False,
                                         marker=dict(symbol="x-thin", size=9, line=dict(width=2, color="#d2a8ff")),
                                         hovertext=f"{w['side']} liquidity sweep · {w['name']}", hoverinfo="text"),
                              row=1, col=1)
    for ob in order_blocks(base) if "Order blocks" in layers else []:
        if ob["time"] >= view.index[0] - step * 40:
            c = "0,229,192" if ob["type"] == "bullish" else "255,77,109"
            fig.add_shape(type="rect", x0=max(ob["time"], view.index[0]), x1=right, y0=ob["bottom"], y1=ob["top"], row=1, col=1,
                          fillcolor=f"rgba({c},.13)", line=dict(color=f"rgba({c},.55)", width=1))
            fig.add_annotation(x=max(ob["time"], view.index[0]), y=ob["bottom"], text="OB", showarrow=False,
                               xanchor="left", yanchor="top", bgcolor="rgba(10,22,38,.9)", bordercolor=f"rgb({c})",
                               borderpad=2, font=dict(size=10, color=f"rgb({c})"), row=1, col=1)
            lo, hi = min(lo, ob["bottom"]), max(hi, ob["top"])

    if show_struct:
        add_structure(fig, closed_only(df, tf), view.index[0])
    if PLAN_MODE and STRAT:
        P = plan_state(symbol, tf, source, STRAT, df.index[-1])
        res = add_plan_trades(fig, P, view.index[0], initial.index[0], view.index[-1], step)
        if res is not None:
            fig.add_annotation(xref="paper", yref="paper", x=0.005, y=0.995, xanchor="left", yanchor="top", showarrow=False,
                               text=T("{s} on this chart: {n} trades · won {w} · lost {l} · total {t}R",
                                      s=T(STRAT_LABEL[STRAT]), n=res["n"], w=res["won"], l=res["lost"], t=f"{res['total']:+.1f}"),
                               bgcolor="rgba(10,22,38,.85)", bordercolor="rgba(0,229,255,.35)", borderpad=4,
                               font=dict(size=10, color=hud.TEXT))
    # GainzAlgo-style BUY / SELL marks with their real outcome (engine mode)
    if S["scalp"] and not PLAN_MODE:
        try:
            hist = signal_history(symbol, tf, source, closed_only(df, tf).index[-1])
        except Exception:  # noqa: BLE001
            hist = pd.DataFrame()
        cache, _ = get_backtest(symbol, tf)
        if cache is not None and not cache.empty:
            old = cache[cache["time"] < (hist["time"].min() if not hist.empty else view.index[-1])].copy()
            old = old[old["time"] >= view.index[0]]
            if not old.empty:
                old["final_grade"] = [bt.cap_grade(g, bt.evidence_cap(bt.edge(cache, n))[0])
                                      for g, n in zip(old["grade"], old["setup"])]
                old["open"] = False
                hist = pd.concat([old, hist], ignore_index=True) if not hist.empty else old
        if not hist.empty:
            shown = ["A+", "A"]
            vis = hist[(hist["time"] >= view.index[0]) & hist["filled"] & hist["final_grade"].isin(shown)]
            vis = vis.drop_duplicates(subset=["time", "setup", "side"])
            won = lost = opn = 0
            for _, r in vis.iterrows():
                if r["time"] not in view.index:
                    continue
                bar = view.loc[r["time"]]
                buy = r["side"] == "LONG"
                if r["open"]:
                    mark, opn = "⏳", opn + 1
                elif r["r"] > 0:
                    mark, won = "✓", won + 1
                else:
                    mark, lost = "✗", lost + 1
                col = UP if buy else DOWN
                y = bar.low - 0.6 * bar.atr if buy else bar.high + 0.6 * bar.atr
                fig.add_trace(go.Scatter(
                    x=[r["time"]], y=[y], mode="markers+text", showlegend=False,
                    marker=dict(symbol="triangle-up" if buy else "triangle-down", size=13, color=col,
                                line=dict(width=1, color="#04070d"), opacity=0.55 if mark == "✗" else 1),
                    text=[f"{T('BUY') if buy else T('SELL')} {r['final_grade']} {mark}"],
                    textposition="bottom center" if buy else "top center",
                    textfont=dict(size=10, color=col, family="JetBrains Mono"),
                    hovertext=f"{setup_name(r['setup'])} · {r['final_grade']} · {r['outcome']} · {r['r']:+.2f}R",
                    hoverinfo="text"), row=1, col=1)
                if r["time"] >= initial.index[0]:
                    lo, hi = min(lo, y), max(hi, y)
            if True:
                summary = (T("Signals in view: {n} · won {w} · lost {l} · open {o}", n=won + lost + opn, w=won, l=lost, o=opn)
                           if len(vis) else T("No tradeable (A/A+) signals in view - no-edge B/C signals are hidden"))
                fig.add_annotation(xref="paper", yref="paper", x=0.005, y=0.995, xanchor="left", yanchor="top", showarrow=False,
                                   text=summary,
                                   bgcolor="rgba(10,22,38,.85)", bordercolor="rgba(0,229,255,.35)", borderpad=4,
                                   font=dict(size=10, color=hud.TEXT))

    for a_ in parse_alerts():
        fig.add_hline(y=a_, line=dict(color="#d2a8ff", width=1, dash="dash"), row=1, col=1)
        badge(fig, a_, f"🔔 {fmt(a_, D)}", "#d2a8ff")

    if sig and not sig.get("plan"):
        try:
            e, sl = float(sig["entry"]), float(sig["stop_loss"])
            tps = [float(sig[k]) for k in ("tp1", "tp2", "tp3")]
            r1 = abs(e - sl) or 1e-9
            x0 = view.index[-1] - step * 3
            x1 = view.index[-1] + step * max(8, int(sig.get("valid_minutes", 45) / TIMEFRAMES[tf][1]))
            alpha = .07 if sig.get("decision") == "NO_TRADE" else .16
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=e, y1=sl, line_width=0, fillcolor=f"rgba(255,77,109,{alpha})", row=1, col=1)
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=e, y1=tps[1], line_width=0, fillcolor=f"rgba(0,229,192,{alpha})", row=1, col=1)
            levels = [(T("Entry"), e, "#ffffff"), ("SL 1R", sl, DOWN)] + \
                     [(f"TP{i} {abs(t - e) / r1:.1f}R", t, UP) for i, t in enumerate(tps, 1)]
            for lbl, y, c in levels:
                fig.add_shape(type="line", x0=x0, x1=x1, y0=y, y1=y, line=dict(color=c, width=1, dash="dash" if lbl == T("Entry") else "solid"),
                              row=1, col=1)
                fig.add_annotation(x=x1, y=y, text=lbl, showarrow=False, xanchor="right", yanchor="bottom",
                                   font=dict(size=10, color=c), row=1, col=1)
                badge(fig, y, fmt(y, D), c)
            lo, hi = min(lo, sl, tps[1]), max(hi, sl, tps[1])
            for i, sc in enumerate(sig.get("scenarios", [])[:3]):
                path = [S["analyses"][0].price] + [float(p) for p in sc.get("path", [])]
                xs = [view.index[-1] + (x1 - view.index[-1]) * j / (len(path) - 1) for j in range(len(path))]
                fig.add_trace(go.Scatter(x=xs, y=path, mode="lines", name=f"{sc.get('name')} {sc.get('probability')}%",
                                         line=dict(dash="dash", width=1.2, color=["#7ee2b8", "#f0a0a0", "#8b949e"][i])),
                              row=1, col=1)
        except (KeyError, TypeError, ValueError):
            pass

    last = view.iloc[-1]
    badge(fig, last.close, fmt(last.close, D), UP if last.close >= last.open else DOWN, "#04070d")

    # lower panel: RSI, volume or MACD
    if lower_panel == "Volume":
        vcol = [UP if c_ >= o_ else DOWN for c_, o_ in zip(view.close, view.open)]
        fig.add_trace(go.Bar(x=view.index, y=view.volume, name="Volume", showlegend=False, marker_color=vcol, opacity=0.6),
                      row=2, col=1)
        fig.add_trace(go.Scatter(x=view.index, y=view.volume.rolling(20).mean(), name="Vol avg 20", showlegend=False,
                                 line=dict(color=hud.AMBER, width=1.2)), row=2, col=1)
    elif lower_panel == "MACD":
        fig.add_trace(go.Bar(x=view.index, y=view.macd_hist, name="MACD hist", showlegend=False,
                             marker_color=[UP if v >= 0 else DOWN for v in view.macd_hist.fillna(0)], opacity=0.6), row=2, col=1)
        fig.add_trace(go.Scatter(x=view.index, y=view.macd, name="MACD", showlegend=False, line=dict(color="#4dd8ff", width=1.2)),
                      row=2, col=1)
        fig.add_trace(go.Scatter(x=view.index, y=view.macd_signal, name="Signal", showlegend=False,
                                 line=dict(color=hud.AMBER, width=1.2)), row=2, col=1)
    else:
        fig.add_trace(go.Scatter(x=view.index, y=view.rsi, name="RSI 14", showlegend=False,
                                 line=dict(color="#a78bfa", width=1.3)), row=2, col=1)
        for lvl in (30, 70):
            fig.add_hline(y=lvl, line=dict(color="rgba(167,139,250,.35)", width=1, dash="dot"), row=2, col=1)
        badge(fig, float(last.rsi), f"{last.rsi:.1f}", "#a78bfa", "#ffffff", yref="y2")
    fig.add_annotation(xref="paper", yref="y2 domain", x=0.0, y=0.98, text={"RSI": "RSI 14", "Volume": "VOLUME (tick)",
                       "MACD": "MACD 12/26/9"}[lower_panel], showarrow=False, xanchor="left", yanchor="top", font=dict(size=10, color=MUTED))

    fig.update_layout(height=640, margin=dict(l=0, r=84, t=10, b=0), paper_bgcolor=BG, plot_bgcolor="rgba(4,10,20,.55)",
                      font=dict(color=MUTED, size=11, family="JetBrains Mono"), xaxis_rangeslider_visible=False,
                      hovermode="x unified", hoverlabel=dict(bgcolor="#0a1626", bordercolor=hud.CYAN, font=dict(color="#fff")),
                      legend=dict(orientation="h", y=1.03, x=0, font=dict(size=10), bgcolor="rgba(0,0,0,0)"),
                      dragmode="pan", uirevision=f"{key}-{st.session_state.get('chart_rev', 0)}")
    fig.update_yaxes(side="right", gridcolor=GRID, tickformat=f".{D}f", row=1, col=1, range=[lo - pad, hi + pad])
    if lower_panel == "RSI":
        fig.update_yaxes(side="right", gridcolor=GRID, range=[0, 100], tickvals=[30, 50, 70], row=2, col=1)
    else:
        fig.update_yaxes(side="right", gridcolor=GRID, row=2, col=1)
    fig.update_xaxes(gridcolor=GRID, rangeslider_visible=False,
                     range=[initial.index[0], view.index[-1] + step * 14])
    if not symbol.startswith("BTC") and tf == "D1":
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig


CHART_CONFIG = {"scrollZoom": True, "displaylogo": False, "doubleClick": "reset",
                "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
                "modeBarButtonsToAdd": [], "displayModeBar": True}


# ---------------------------------------------------------------- ticket

def verdict_html(sig, S):
    """Big plain-language decision + levels + plan."""
    ctx = S["ctx"]
    if not sig:
        best = S["setups"][0] if S["setups"] else None
        if best:
            line = f"{T('Engine sees:')} <b>{side_txt(best.side)} · {quality_word(best.grade)}</b> · {setup_name(best.name)}"
        else:
            line = T("No clean setup on the radar.")
        return (f"<div class='hud verdict'><div class='hud-t'>{T('Decision')}</div>"
                f"<div class='act' style='color:{hud.CYAN}'>{T('STANDBY')}</div>"
                f"<div class='sub'>{line}<br><span class='muted'>{T('Press <b>ANALYZE</b> for the full AI read.')}</span></div></div>")
    dec = sig.get("decision", "NO_TRADE")
    color = {"LONG": UP, "SHORT": DOWN}.get(dec, hud.AMBER)
    ot = order_txt(sig.get("order_type"))
    if dec in ("LONG", "SHORT"):
        act = ot if ot != "—" else T("BUY" if dec == "LONG" else "SELL")
        try:
            act += f" <span class='mono'>{fmt(sig['entry'], D)}</span>"
        except (KeyError, TypeError, ValueError):
            pass
        sub = sig.get("summary", "")
    else:
        act = T("WAIT")
        sub = tr_dyn((sig.get("warnings") or [sig.get("summary", "")])[0])
    rows, extra = "", ""
    try:
        e, sl = float(sig["entry"]), float(sig["stop_loss"])
        tps = [float(sig[k]) for k in ("tp1", "tp2", "tp3")]
        ps = position_size(symbol, e, sl, balance, risk_pct, int(leverage), lot_size)
        r = abs(e - sl) or 1e-9
        rows += f"<tr><td class='l'>{T('Entry')}</td><td><b>{fmt(e, D)}</b></td><td class='r'>{ot}</td></tr>"
        rows += (f"<tr><td class='l'>{T('Stop')}</td><td style='color:{DOWN}'>{fmt(sl, D)}</td>"
                 f"<td class='r'>{abs(e - sl) / inst.pip:.0f} {T('pips')} · -&#36;{ps['risk_usd']:,.2f}</td></tr>")
        for i, t in enumerate(tps, 1):
            rows += (f"<tr><td class='l'>{T('Target {i}', i=i)}</td><td style='color:{UP}'>{fmt(t, D)}</td>"
                     f"<td class='r'>{abs(t - e) / r:.1f}R · +&#36;{reward_usd(symbol, e, t, ps['lots']):,.2f}</td></tr>")
        lot_line = T("{lots} lot · risk {p}% (${r}) · margin ${m} @1:{lev}", lots=f"{ps['lots']:.2f}", p=ps["actual_risk_pct"],
                     r=f"{ps['risk_usd']:,.2f}", m=f"{ps['margin_usd']:,.2f}", lev=leverage).replace("$", "&#36;")
        lot_line += " · " + T("pip value {pv} USD", pv=f"{ps['pip_value_usd']:,.2f}")
        extra = f"<div class='txt muted mono' style='margin-top:8px'>{lot_line}</div>"
        for w in ps["warnings"]:
            extra += f"<div class='bad'>⚠ {tr_dyn(w)}</div>"
    except (KeyError, TypeError, ValueError):
        rows = f"<tr><td>{T('Levels unavailable')}</td></tr>"
    for w in (sig.get("warnings") or [])[1 if dec == "NO_TRADE" else 0:]:
        extra += f"<div class='warn'>⚠ {tr_dyn(w)}</div>"
    created = sig.get("created")
    valid = ""
    if created is not None and sig.get("valid_minutes"):
        until = created + timedelta(minutes=float(sig["valid_minutes"]))
        expired = pd.Timestamp.now(tz="UTC") > until
        valid = (f"{T('EXPIRED') if expired else T('VALID UNTIL')} {until:%H:%M} UTC · {T('signal')} {created:%H:%M} "
                 f"@ {fmt(sig.get('price_at_signal', 0), D)}")
    block = lambda lbl, txt: f"<div class='lbl'>{lbl}</div><div class='txt'>{txt}</div>" if txt else ""
    e = edge_for(get_backtest(symbol, tf)[0], sig.get("setup"))
    canon = canonical_setup(sig.get("setup"))
    match = next((x for x in S["setups"] if x.name == canon), None)
    sim = getattr(match, "quality", None) if match else None
    lang_note = ""
    if sig.get("lang", "en") != i18n.lang():
        names = {v: k for k, v in i18n.LANGS.items()}
        lang_note = f"<div class='warn'>🌐 {T('This analysis was written in {l}. Press Analyze to refresh it in the current language.', l=names.get(sig.get('lang', 'en'), 'English'))}</div>"
    return f"""<div class="hud verdict" style="border-color:{color}55">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
    <div><div class="hud-t">{T('Decision')} · {setup_name(canonical_setup(sig.get('setup', '')))}</div>
      <div class="act" style="color:{color};text-shadow:0 0 18px {color}66">{act}</div></div>
    {hud.ring({'A+': 90, 'A': 75, 'B': 55, 'C': 30}.get(sig.get('grade'), 20), color, T('QUALITY'))}
  </div>
  <div class="sub">{sub}</div>{lang_note}
  <table>{rows}</table>{extra}
  {block(T('Trigger'), sig.get('trigger', ''))}
  {block(T('Plan'), sig.get('management', ''))}
  {block(T('Backtest edge'), edge_txt(e))}
  {block(T('Similar past setups'), similar_txt(sim))}
  <div class="txt muted mono" style="margin-top:10px;font-size:.72rem">{valid}<br>{sig.get('engine', '')}</div>
</div>"""


def checklist_items(S, sig):
    """Green / amber / red reasons for the current idea (signal, else best radar setup)."""
    ctx = S["ctx"]
    best = S["setups"][0] if S["setups"] else None
    if sig and sig.get("decision") in ("LONG", "SHORT"):
        d, name = (1 if sig["decision"] == "LONG" else -1), sig.get("setup")
        entry, stop = sig.get("entry"), sig.get("stop_loss")
    elif best:
        d, name, entry, stop = best.direction, best.name, best.entry, best.stop
    else:
        return [(T("No setup to check"), "na", "")]
    items = []
    bias = mtf_score(S["analyses"][1:]) if len(S["analyses"]) > 1 else S["analyses"][0].score
    items.append((T("Higher-timeframe trend agrees"), "ok" if bias * d > 15 else "bad" if bias * d < -15 else "warn", f"{bias:+.0f}"))
    q = ctx.session["quality"] if ctx else "active"
    items.append((T("Good session timing"), "ok" if q in ("prime", "active") else "bad" if "closed" in q else "warn", quality_txt(q)))
    e = edge_for(get_backtest(symbol, tf)[0], name)
    items.append((T("Setup has a backtest edge"),
                  "warn" if not e else "ok" if e["avg_r"] >= 0.05 else "warn" if e["avg_r"] > -0.05 else "bad",
                  f"{e['avg_r']:+.2f}R · {e['n']}" if e else T("untested")))
    now = pd.Timestamp.now(tz="UTC")
    nxt = next((x for x in S["events"] if x["impact"] == "High" and x["time"] > now - pd.Timedelta(minutes=15)), None)
    mins = (nxt["time"] - now).total_seconds() / 60 if nxt else None
    items.append((T("No big news soon"), "ok" if mins is None or mins > 120 else "warn" if mins > 60 else "bad",
                  T("clear") if mins is None else T("{n} min", n=int(mins))))
    if ctx and ctx.inter:
        im = ctx.inter
        items.append((T("{name} confirms", name=im["name"]), "ok" if im["bias"] == d else "bad" if im["bias"] == -d else "warn",
                      f"{im['chg_pct']:+.2f}%"))
    if ctx and ctx.adr_used is not None:
        u = ctx.adr_used
        items.append((T("Room left in today's range"), "ok" if u < 80 else "warn" if u < 100 else "bad", T("{u}% used", u=f"{u:.0f}")))
    try:
        risk = abs(float(entry) - float(stop))
        cost = (ctx.spread if ctx else 0) / risk
        items.append((T("Spread cost small"), "ok" if cost < 0.10 else "warn" if cost < 0.15 else "bad", f"{cost:.2f}R"))
        ps = position_size(symbol, float(entry), float(stop), balance, risk_pct, int(leverage), lot_size)
        rp = ps["actual_risk_pct"]
        items.append((T("Account risk acceptable"), "ok" if rp <= max(1.5 * risk_pct, 1) else "warn" if rp <= 5 else "bad", f"{rp:.1f}%"))
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    items.append((T("Daily risk guard"), "bad" if guard["blocked"] else "ok", "STOP" if guard["blocked"] else f"{guard['trades']}/{max_trades}"))
    return items


def gauges_html(S):
    ctx = S["ctx"]
    bias = mtf_score(S["analyses"][1:]) if len(S["analyses"]) > 1 else S["analyses"][0].score
    bcol = UP if bias > 15 else DOWN if bias < -15 else hud.AMBER
    if bias > 15:
        bcap = "Strong bullish" if bias > 50 else "Bullish"
    elif bias < -15:
        bcap = "Strong bearish" if bias < -50 else "Bearish"
    else:
        bcap = "No clear trend"
    out = [hud.gauge(T("Trend bias"), bias, -100, 100, f"{bias:+.0f}", T(bcap), bcol, center_zero=True)]
    if ctx:
        z = ctx.vwap_z
        zcap = "Far above fair value" if z > 1.5 else "Above fair value" if z > 0.3 else \
               "Far below fair value" if z < -1.5 else "Below fair value" if z < -0.3 else "At fair value"
        out.append(hud.gauge(T("Price vs VWAP"), z, -3, 3, f"{z:+.1f}σ", T(zcap), hud.AMBER if abs(z) > 1.5 else hud.CYAN, center_zero=True))
        if ctx.adr_used is not None:
            u = ctx.adr_used
            out.append(hud.gauge(T("Day range used"), u, 0, 150, f"{u:.0f}%",
                                 T("Exhausted - late to chase" if u >= 100 else "Getting stretched" if u >= 80 else "Plenty of room"),
                                 DOWN if u >= 100 else hud.AMBER if u >= 80 else UP))
    board = get_board()
    if board:
        m = macro.risk_mood(board)
        out.append(hud.gauge(T("Market mood"), m["score"], -2, 2, T(m["mood"].upper()),
                             T({"risk-on": "Investors buying risk", "risk-off": "Investors seeking safety"}.get(m["mood"], "Mixed signals")),
                             {"risk-on": UP, "risk-off": DOWN}.get(m["mood"], hud.AMBER), center_zero=True))
    return out


# ---------------------------------------------------------------- plan mode (user's strategies + trailing exit)

def plan_open_trade(P):
    if not P or not P["trades"]:
        return None
    t = P["trades"][-1]
    return t if t.get("open") or t.get("exit_i") is None else None


def plan_base_signal(P):
    """Signal dict for the plan: the strategy decides, the AI only explains."""
    base = {"plan": True, "strategy": STRAT, "setup": STRAT_LABEL.get(STRAT, ""), "engine": T("Rule-based plan"),
            "valid_minutes": TIMEFRAMES[tf][1] * 4}
    if not STRAT:
        base.update(decision="NO_TRADE", summary=T("Neither of your strategies made money on {sym} in testing - no trades here.", sym=symbol))
        return base
    ot = plan_open_trade(P)
    if ot:
        side = "LONG" if ot["side"] == 1 else "SHORT"
        base.update(decision=side, entry=ot["entry"], stop_loss=ot.get("stop_now", ot["stop0"]), stop0=ot["stop0"],
                    open_r=ot.get("open_r", 0.0), since=str(ot["time"]),
                    fresh=ot["time"] == P["last_time"],
                    summary=T("In a {side} trade since {t} UTC. The stop now trails at {s}.", side=T(side),
                              t=f"{ot['time']:%m-%d %H:%M}", s=fmt(ot.get('stop_now', ot['stop0']), D)))
    else:
        base.update(decision="NO_TRADE", summary=plan_wait_text(P["checks"]))
    return base


def plan_wait_text(chk):
    if STRAT and STRAT.startswith("mr_"):
        m = chk["mr"]
        if STRAT == "mr_gold":
            if not m["uptrend"] or m.get("dtrend") != 1:
                return T("Gold buys dips only while the daily trend and the H1 trend are both up - that is not the case now, so it waits.")
            if not m["calm"]:
                return T("A news-spike candle printed in the last 3 hours - signals paused until the market calms down.")
            if m.get("breakdown"):
                return T("Price just broke the last 30 candles' range (LL/BOS) - that is a structure break, not a dip, so signals wait.")
            if m.get("usd_wide") is not None and not m["usd_wide"] < meanrev.USD_WIDE_MAX:
                return T("The whole US dollar is moving (EURUSD moved as much as gold) - signals wait.")
            return T("Uptrend on H1 and daily: waiting to BUY a deep dip (RSI(2) under 2). Now RSI(2) {v}.", v=f"{m['level']:.0f}")
        if STRAT == "mr_eur":
            if not m["calm"]:
                return T("A news-spike candle printed in the last 3 hours - signals paused until the market calms down.")
            if m.get("breakdown"):
                return T("Price just broke the last 30 candles' range (LL/BOS) - that is a structure break, not a dip, so signals wait.")
            if m.get("usd_wide") is not None and not m["usd_wide"] < meanrev.USD_WIDE_MAX:
                return T("The whole US dollar is moving (GBPUSD moved as much as EURUSD) - snap-backs had no edge in that case, so signals wait.")
            if m["uptrend"]:
                return T("Uptrend (above the 200-average): waiting to BUY a dip - RSI(2) under 2, or the last 2 candles' RSI(2) adding up to under 10. Now {v}.",
                         v=f"RSI(2) {m['level']:.0f} · 2-candle {m['cum2']:.0f}")
            return T("Downtrend (below the 200-average): waiting to SELL a sharp rally - RSI(2) above 98. Now RSI(2) {v}.", v=f"{m['level']:.0f}")
        if not m["uptrend"]:
            return T("Price is below its 200-period average - dip-buying is paused until the uptrend returns.")
        return T("Uptrend confirmed. Waiting for a sharp dip ({what}) to buy.", what=T(
            {"mr_d7": "close at a 7-period low", "mr_rsi2": "RSI(2) below 5",
             "mr_rsi2x": "RSI(2) below 2 with no news spike"}.get(STRAT, "sharp dip")))
    if STRAT != "pro":
        return T("Waiting for a Signal v26 setup (trend + RSI + engulfing/pin bar + volume).")
    if not chk["trend"]:
        return T("4H trend is unclear (EMA50/EMA200 not aligned) - no trades until it is.")
    missing = [T(n) for k, n in (("session", "active session"), ("adx_ok", "ADX ≥ 20"), ("structure", "structure"),
                                 ("pullback", "pullback to EMA20"), ("confirm", "confirmation candle")) if not chk[k]]
    if chk.get("daily") != chk["trend"]:
        missing.insert(0, T("daily trend to agree"))
    if not chk.get("not_monday", True):
        missing.insert(0, T("Tuesday (no Monday trades)"))
    side = T("LONG") if chk["trend"] == 1 else T("SHORT")
    return T("4H trend says {side} only. Waiting for: {m}.", side=side, m=", ".join(missing) or T("stop within 3×ATR"))


def plan_prompt_text(P):
    if not P:
        return "No strategy is active on this market (both lose in testing)."
    chk = P["checks"]
    sh, stf = plan_stats(STRAT, symbol, tf)
    ot = plan_open_trade(P)
    exit_txt = ("exits on the bounce (mean reversion); stop 1.5xATR, half off at TP1 = 1R then stop to breakeven"
                if STRAT.startswith("mr_") and meanrev.exit_cfg(symbol, STRAT)["tp1_r"] else
                "exits on the bounce (mean reversion) with a 3xATR safety stop" if STRAT.startswith("mr_") else
                "exits at a fixed +0.5R target" if STRAT == "v26_t05" else "exits with a Chandelier trailing stop (3xATR behind the best price)")
    lines = [f"RULE-BASED PLAN ({STRAT_LABEL[STRAT]}), {exit_txt}.",
             f"Tested: {sh['n']} trades, win {sh['win']:.0f}%, {sh['avg_r']:+.2f}R/trade, PF {sh['pf']:.2f} on {stf}." if sh else "",
             (f"Mean-reversion state: uptrend {chk['mr']['uptrend']}, dip signal {chk['mr']['dip']}, exit level {chk['mr']['target']:.{D}f}."
              if "mr" in chk else
              f"4H trend: {['down', 'unclear', 'up'][chk['trend'] + 1]}; ADX {chk['adx']:.0f}; session active: {chk['session']}; "
              f"structure {chk['structure']}; pullback {chk['pullback']}; confirmation {chk['confirm']}.")]
    if ot:
        lines.append(f"STATE: IN A {'LONG' if ot['side'] == 1 else 'SHORT'} TRADE since {ot['time']}, entry {ot['entry']:.{D}f}, "
                     f"trailing stop now {ot.get('stop_now', ot['stop0']):.{D}f}, open {ot.get('open_r', 0):+.2f}R.")
    else:
        lines.append("STATE: WAITING - no entry signal on the last closed candle.")
    if "mr" not in chk:
        lines.append(f"Pro rules also applied: daily trend {['down', 'unclear', 'up'][chk.get('daily', 0) + 1]} must agree; no Monday entries.")
    lines.append("Your job: explain this in plain words for the trader, check the news/macro risk, and say if a high-impact "
                 "event in the next hour is a reason to skip. The plan's decision stands unless news is a real danger.")
    return "\n".join(x for x in lines if x)


def plan_verdict_html(sig, S, P):
    sh, stf = plan_stats(STRAT, symbol, tf) if STRAT else (None, None)
    ot = plan_open_trade(P)
    if not STRAT:
        act, color = T("WAIT"), hud.AMBER
        sub = T("Neither of your strategies made money on {sym} in testing - no trades here.", sym=symbol)
    elif ot:
        side = "LONG" if ot["side"] == 1 else "SHORT"
        color = UP if ot["side"] == 1 else DOWN
        fresh = ot["time"] == P["last_time"]
        act = (T("BUY") if ot["side"] == 1 else T("SELL")) + f" <span class='mono'>{fmt(ot['entry'], D)}</span>" if fresh \
            else T("IN TRADE") + " · " + T(side)
        sub = T("New signal on the last closed candle.") if fresh else \
            T("Open since {t} UTC · now {r}R", t=f"{ot['time'] + P.get('shift', pd.Timedelta(0)):%m-%d %H:%M}", r=f"{ot.get('open_r', 0):+.2f}")
    else:
        act, color = T("WAIT"), hud.AMBER
        sub = plan_wait_text(P["checks"]) if P else ""
        last = P["trades"][-1] if P and P["trades"] else None
        if last:
            sub += "<br>" + T("Last signal: {side} at {e} on {t} UTC → {r}R", side=T("BUY") if last["side"] == 1 else T("SELL"),
                              e=fmt(last["entry"], D), t=f"{last['time'] + P.get('shift', pd.Timedelta(0)):%m-%d %H:%M}",
                              r=f"{last['r']:+.2f}")
    rows, extra = "", ""
    if ot:
        stop_now = ot.get("stop_now", ot["stop0"])
        ps = position_size(symbol, ot["entry"], ot["stop0"], balance, risk_pct, int(leverage), lot_size)
        rows += f"<tr><td class='l'>{T('Entry')}</td><td><b>{fmt(ot['entry'], D)}</b></td><td class='r'>{ot['time'] + P.get('shift', pd.Timedelta(0)):%m-%d %H:%M}</td></tr>"
        rows += (f"<tr><td class='l'>{T('Initial stop')}</td><td style='color:{DOWN}'>{fmt(ot['stop0'], D)}</td>"
                 f"<td class='r'>1R = {abs(ot['entry'] - ot['stop0']) / inst.pip:.0f} {T('pips')} · -&#36;{ps['risk_usd']:,.2f}</td></tr>")
        R0 = abs(ot["entry"] - ot["stop0"])
        for k_, ((v, lv, pct), ok) in enumerate(zip(ot.get("tps") or [], ot.get("tp_hit") or []), 1):
            usd = abs(v - ot["entry"]) / R0 * ps["risk_usd"]
            rows += (f"<tr><td class='l'>TP{k_}</td><td style='color:{UP}'>{fmt(v, D)}{' ✓' if ok else ''}</td>"
                     f"<td class='r'>+{abs(v - ot['entry']) / inst.pip:.0f} {T('pips')} · +&#36;{usd:,.2f} · "
                     f"{T('HIT') if ok else T('{p}% of past trades reached it', p=pct)}"
                     f"{' · ' + T('close half, SL to breakeven') if k_ == 1 and ot.get('tp1') else ''}</td></tr>")
        tps = sorted([(v, n) for v, n in ((None if ot.get("tps") else ot.get("tp1"), T("close half, SL to breakeven")),
                                          (ot.get("target_now") if STRAT.startswith("mr_") else None, T("exit on the bounce"))) if v],
                     key=lambda x: abs(x[0] - ot["entry"]))
        for k_, (v, note) in enumerate(tps, 1):
            lbl = f"TP{k_}" if ot.get("tp1") and not ot.get("tps") else T("Exit level now")
            if v:
                rows += (f"<tr><td class='l'>{lbl}</td><td style='color:{UP}'>{fmt(v, D)}</td>"
                         f"<td class='r'>R:R 1:{abs(v - ot['entry']) / R0:.1f} · +&#36;{abs(v - ot['entry']) / R0 * ps['risk_usd']:,.2f} · {note}</td></tr>")
        stop_lbl = T("Stop now") if STRAT.startswith("mr_") else T("Trailing stop now")
        rows += (f"<tr><td class='l'>{stop_lbl}</td><td style='color:{hud.AMBER}'>{fmt(stop_now, D)}</td>"
                 f"<td class='r'>{(stop_now - ot['entry']) * ot['side'] / R0:+.2f}R "
                 f"{T('locked') if (stop_now - ot['entry']) * ot['side'] >= 0 else T('if hit')}</td></tr>")
        lot_line = T("{lots} lot · risk {p}% (${r}) · margin ${m} @1:{lev}", lots=f"{ps['lots']:.2f}", p=ps["actual_risk_pct"],
                     r=f"{ps['risk_usd']:,.2f}", m=f"{ps['margin_usd']:,.2f}", lev=leverage).replace("$", "&#36;")
        lot_line += " · " + T("pip value {pv} USD", pv=f"{ps['pip_value_usd']:,.2f}")
        extra = f"<div class='txt muted mono' style='margin-top:8px'>{lot_line}</div>"
        for w in ps["warnings"]:
            extra += f"<div class='bad'>⚠ {tr_dyn(w)}</div>"
    for w in (sig or {}).get("warnings", []):
        extra += f"<div class='warn'>⚠ {tr_dyn(w)}</div>"
    if ot and ot["time"] == P["last_time"]:
        now = pd.Timestamp.now(tz="UTC")
        soon = [x for x in newsmod.relevant_events(get_calendar(), symbol)
                if x["impact"] == "High" and now - pd.Timedelta(minutes=15) <= x["time"] <= now + pd.Timedelta(minutes=60)]
        if soon:
            msg = T("High-impact news at {t} UTC ({e}) - wait until it is out and the candle closes calm.",
                    t=f"{soon[0]['time']:%H:%M}", e=soon[0].get("title", ""))
            extra += f"<div class='bad'>📰 {msg}</div>"
    if sig and sig.get("ai_decision") == "NO_TRADE" and ot and ot["time"] == P["last_time"]:
        extra += f"<div class='warn'>🧠 {T('DeepSeek suggests caution on this entry - read the analysis below.')}</div>"
    block = lambda lbl, txt: f"<div class='lbl'>{lbl}</div><div class='txt'>{txt}</div>" if txt else ""
    tested = (T("{n} trades · win {w}% · {r}R per trade · PF {pf} · worst drawdown {dd}R ({tf})", n=sh["n"], w=f"{sh['win']:.0f}",
                r=f"{sh['avg_r']:+.2f}", pf=f"{sh['pf']:.2f}", dd=f"{sh['max_dd']:.0f}", tf=stf + test_span(sh))
              if sh else T("untested"))
    win = sh["win"] if sh else 0
    ai_txt = (sig or {}).get("summary") if sig and sig.get("plan") and sig.get("ai_decision") else ""
    return f"""<div class="hud verdict" style="border-color:{color}55">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
    <div><div class="hud-t">{T('Decision')} · {T(STRAT_LABEL.get(STRAT, '-')) if STRAT else '-'}</div>
      <div class="act" style="color:{color};text-shadow:0 0 18px {color}66">{act}</div></div>
    {hud.ring(win, color, T('WIN RATE'))}
  </div>
  <div class="sub">{sub}</div>
  <table>{rows}</table>{extra}
  {block(T('Exit plan'), exit_plan_txt()) if STRAT else ''}
  {block(T('Tested on this market'), tested)}
  {block(T('AI view'), ai_txt)}
</div>"""


def test_span(sh):
    """' · 10y' from the stats' date range, plus the older/newer split when it was stored."""
    try:
        yrs = round((pd.Timestamp(sh["to"]) - pd.Timestamp(sh["from"])).days / 365.25)
    except (KeyError, ValueError, TypeError):
        return ""
    out = f" · {yrs}y"
    if "pf_train" in sh:
        out += " · " + T("PF older {a} / newer {b}", a=f"{sh['pf_train']:.2f}", b=f"{sh['pf_test']:.2f}")
    if STRAT == "mr_gold":
        out += ". " + T("Assumes ~$0.25 total cost per ounce (Razor). At $0.35 the same test wins 86%, at $0.50 73%. "
                        "Gold is volatile now: a full stop at 0.01 lot is about $44.")
    if STRAT == "mr_eur":                       # TP1 is only a few pips, so trading costs move the win rate a lot
        out += ". " + T("Assumes ~0.9 pip total cost (Pepperstone Razor: raw spread + commission). On a Standard account "
                        "(~1.2 pips) the same test wins 77%; at 1.5 pips 65%.")
    return out


def exit_plan_txt():
    if STRAT.startswith("mr_"):
        lv = meanrev.TP_LEVELS.get(STRAT)
        tp_note = (" " + T("TP1/TP2/TP3 show how far past signals ran: {a}% reached TP1, {b}% TP2, {c}% TP3. Safer option: close 1/3 at "
                           "each TP and move the stop to breakeven after TP1 - won 80% of trades in testing, but about 40% less profit "
                           "than holding to the bounce exit.", a=lv[0][1], b=lv[1][1], c=lv[2][1])) if lv else ""
        if STRAT == "mr_gold":
            return T("Stop 3×ATR from entry. TP1 (+0.25×ATR): close HALF and move the stop to breakeven - {a}% of past trades reached "
                     "it. The other half: close when an H1 candle closes back above the 5-period average (the snap-back). TP2/TP3 show "
                     "how far moves usually ran ({b}% / {c}%). Buys only deep dips while the daily and H1 trends are up; skipped after a "
                     "news spike, on a structure break, and when the whole dollar is moving (checked against EURUSD). "
                     "You need at least 0.02 lot to close half.", a=lv[0][1], b=lv[1][1], c=lv[2][1])
        if STRAT == "mr_eur":
            return T("Stop 3×ATR from entry. TP1 (+0.25×ATR, a few pips): close HALF and move the stop to breakeven - 85% of past "
                     "trades reached it, which is why 83% of trades ended in profit. The other half: close when a candle closes back "
                     "across the 5-period average (the snap-back). TP2/TP3 show how far moves usually ran ({b}% / {c}%). "
                     "Buys dips in an uptrend, sells rallies in a downtrend; skipped after a news spike, on a structure break (new "
                     "30-candle low/high) and when the whole dollar is moving (checked against GBPUSD). You need at least 0.02 lot to close half.", b=lv[1][1], c=lv[2][1])
        if meanrev.exit_cfg(symbol, STRAT)["tp1_r"]:
            return T("Stop 1.5×ATR below entry. TP1 at 1:1 - close half and move the stop to breakeven. TP2: close the rest when a "
                     "candle closes back above the 5-period average (the bounce). Signals come from the H1 chart and show on any chart.")
        if STRAT == "mr_eur":
            return T("Stop 3×ATR from entry. Target: close the trade when a candle closes back across the 5-period average (the snap-back) - "
                     "usually within a few hours. Buys dips in an uptrend, sells rallies in a downtrend. Skipped after a news-spike candle "
                     "and when the whole dollar is moving (checked against GBPUSD). "
                     "Signals come from the H1 chart and show on any chart.") + tp_note
        if STRAT == "mr_rsi2x":
            return T("Stop 3×ATR below entry. Target: close the trade when a candle closes back above the 5-period average (the bounce) - "
                     "usually within a few hours. Skipped when a news spike candle printed in the last 3 hours. "
                     "Signals come from the H1 chart and show on any chart.") + tp_note
        return T("Sell the bounce: exit when price closes back above the 5-period average / 7-period high. Safety stop 3×ATR below entry.")
    if STRAT == "v26_t05":
        return T("Fixed target at +0.5R, stop at the signal's stop. Small wins most of the time; that is why the win rate is high.")
    return T('No fixed target: the stop trails {k}×ATR behind the best price, so winners can run and losers stay small.',
             k=proplan.TRAIL_ATR.get(STRAT, 3.0))


def plan_checklist(S, P):
    if not STRAT or not P:
        return [(T("Strategy profitable on this market (tested)"), "bad", T("no"))]
    sh, _ = plan_stats(STRAT, symbol, tf)
    items = [(T("Strategy profitable on this market (tested)"), "ok" if sh and sh["avg_r"] > 0 else "bad",
              f"{sh['avg_r']:+.2f}R" if sh else T("untested"))]
    chk = P["checks"]
    if STRAT.startswith("mr_"):
        m = chk["mr"]
        if STRAT == "mr_gold":
            items += [(T("H1 uptrend (above the 200-average)"), "ok" if m["uptrend"] else "bad", fmt(m["sma200"], D)),
                      (T("Daily uptrend (above the 50-day average)"), "ok" if m.get("dtrend") == 1 else "bad",
                       T("yes") if m.get("dtrend") == 1 else T("no")),
                      (T("Deep dip (RSI(2) under 2)"), "ok" if m["dip"] else "warn", f"RSI2 {m['level']:.0f}"),
                      (T("No news spike in the last 3 candles"), "ok" if m["calm"] else "bad", f"{m['spike']:.1f}×ATR"),
                      (T("No structure break (not a new 30-candle low/high)"), "bad" if m.get("breakdown") else "ok",
                       T("break - skip") if m.get("breakdown") else T("clear")),
                      (T("Gold-only move (EURUSD not moving as much)"),
                       "warn" if m.get("usd_wide") is None else "ok" if m["usd_wide"] < meanrev.USD_WIDE_MAX else "bad",
                       T("no EURUSD data") if m.get("usd_wide") is None else f"{m['usd_wide']:.2f} / <{meanrev.USD_WIDE_MAX}"),
                      (T("Exit when price closes back across"), "ok", fmt(m["target"], D))]
        elif STRAT == "mr_eur":
            items += [(T("Trend (200-period average)"), "ok", T("buy dips") if m["uptrend"] else T("sell rallies")),
                      (T("Signal"), "ok" if m["dip"] else "warn", T(m["tier"]) if m["tier"] else f"RSI2 {m['level']:.0f}"),
                      (T("No news spike in the last 3 candles"), "ok" if m["calm"] else "bad", f"{m['spike']:.1f}×ATR"),
                      (T("No structure break (not a new 30-candle low/high)"), "bad" if m.get("breakdown") else "ok",
                       T("break - skip") if m.get("breakdown") else T("clear")),
                      (T("EUR-only move (GBPUSD not moving as much)"),
                       "warn" if m.get("usd_wide") is None else "ok" if m["usd_wide"] < meanrev.USD_WIDE_MAX else "bad",
                       T("no GBPUSD data") if m.get("usd_wide") is None else f"{m['usd_wide']:.2f} / <{meanrev.USD_WIDE_MAX}"),
                      (T("Exit when price closes back across"), "ok", fmt(m["target"], D))]
        else:
            items += [(T("Uptrend (above 200-period average)"), "ok" if m["uptrend"] else "bad", fmt(m["sma200"], D)),
                      (T("Sharp dip signal"), "ok" if m["dip"] else "warn",
                       f"RSI2 {m['level']:.0f}" if STRAT == "mr_rsi2" else fmt(m["level"], D)),
                      (T("Exit when price closes back above"), "ok", fmt(m["target"], D))]
        if "spike" in m and STRAT not in ("mr_eur", "mr_gold"):
            items.insert(-1, (T("No news spike in the last 3 candles"), "ok" if m["calm"] else "bad", f"{m['spike']:.1f}×ATR"))
    if STRAT == "pro":
        items += [(T("4H trend clear (EMA50 vs EMA200)"), "ok" if chk["trend"] else "bad",
                   {1: T("LONG"), -1: T("SHORT"), 0: "—"}[chk["trend"]]),
                  (T("Active session (07-17 UTC)"), "ok" if chk["session"] else "warn", ""),
                  (T("Trending market (ADX ≥ 20)"), "ok" if chk["adx_ok"] else "warn", f"{chk['adx']:.0f}"),
                  (T("Structure holds (EMA20 vs EMA50)"), "ok" if chk["structure"] else "warn", ""),
                  (T("Pulled back to EMA20"), "ok" if chk["pullback"] else "warn", ""),
                  (T("Confirmation candle"), "ok" if chk["confirm"] else "warn", ""),
                  (T("Stop within 3×ATR"), "ok" if chk["stop_ok"] else "warn", "")]
    if "daily" in chk:                                   # trend strategies only (pro rules don't apply to dip-buying)
        if chk.get("trend") or STRAT in ("v26", "v26_t05"):
            want = chk["trend"] if STRAT == "pro" else chk["daily"]
            items.insert(2, (T("Daily trend agrees (pro rule)"), "ok" if chk["daily"] and chk["daily"] == want else "bad",
                             {1: T("LONG"), -1: T("SHORT"), 0: "—"}[chk["daily"]]))
        items.insert(3, (T("Not Monday (pro rule)"), "ok" if chk["not_monday"] else "warn", ""))
    now = pd.Timestamp.now(tz="UTC")
    nxt = next((x for x in S["events"] if x["impact"] == "High" and x["time"] > now - pd.Timedelta(minutes=15)), None)
    mins = (nxt["time"] - now).total_seconds() / 60 if nxt else None
    items.append((T("No big news soon"), "ok" if mins is None or mins > 120 else "warn" if mins > 60 else "bad",
                  T("clear") if mins is None else T("{n} min", n=int(mins))))
    items.append((T("Daily risk guard"), "bad" if guard["blocked"] else "ok", "STOP" if guard["blocked"] else f"{guard['trades']}/{max_trades}"))
    return items


def add_structure(fig, d_closed, view_start):
    """Swing labels (HH/HL/LH/LL) and BOS / CHoCH lines from closed candles."""
    k = 3
    h, l = d_closed["high"].to_numpy(), d_closed["low"].to_numpy()
    n = len(d_closed)
    last_hi = last_lo = None
    xs, ys, txt, cols = [], [], [], []
    for i in range(k, n - k):
        t_ = d_closed.index[i]
        if h[i] == h[i - k:i + k + 1].max():
            lab = "HH" if last_hi is None or h[i] > last_hi else "LH"
            last_hi = h[i]
            if t_ >= view_start:
                xs.append(t_); ys.append(h[i]); txt.append(lab); cols.append(UP if lab == "HH" else hud.AMBER)
        if l[i] == l[i - k:i + k + 1].min():
            lab = "LL" if last_lo is None or l[i] < last_lo else "HL"
            last_lo = l[i]
            if t_ >= view_start:
                xs.append(t_); ys.append(l[i]); txt.append(lab); cols.append(DOWN if lab == "LL" else hud.CYAN)
    if xs:
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="text", text=txt, showlegend=False, hoverinfo="skip",
                                 textfont=dict(size=9, color=cols, family="JetBrains Mono"),
                                 textposition=["top center" if t in ("HH", "LH") else "bottom center" for t in txt]),
                      row=1, col=1)
    for ev in structure_events(d_closed)[-12:]:
        if ev["time"] < view_start:
            continue
        x0 = d_closed.index[max(0, ev["i"] - 12)]
        c = UP if ev["dir"] == 1 else DOWN
        fig.add_shape(type="line", x0=x0, x1=ev["time"], y0=ev["level"], y1=ev["level"], row=1, col=1,
                      line=dict(color=c, width=1, dash="dot"))
        fig.add_annotation(x=ev["time"], y=ev["level"], text=ev["type"], showarrow=False, xanchor="right",
                           yanchor="bottom" if ev["dir"] == 1 else "top", font=dict(size=9, color=c), row=1, col=1)


def add_plan_trades(fig, P, view_start, initial_start, chart_end=None, step=None):
    """Each strategy trade as a position box (red = risk to the stop, green = reward to the target),
    with entry / SL / TP labels on the latest trade, the stop path and the exit mark."""
    if not P:
        return None
    won = lost = 0
    total = 0.0
    sh = P.get("shift", pd.Timedelta(0))
    shown = [t for t in P["trades"] if t["time"] + sh >= view_start]
    for k, t in enumerate(shown):
        buy, side = t["side"] == 1, t["side"]
        col = UP if buy else DOWN
        is_open = t.get("exit_i") is None
        r = t.get("open_r", t["r"]) if is_open else t["r"]
        mark = "⏳" if is_open else ("✓" if r > 0 else "✗")
        if not is_open:
            won += r > 0; lost += r <= 0; total += r
        e, s0 = t["entry"], t["stop0"]
        R = abs(e - s0)
        x0 = t["time"] + sh
        x1 = (t["exit_time"] + sh) if not is_open and t.get("exit_time") is not None else \
            (chart_end + (step or pd.Timedelta(0)) * 10 if chart_end is not None else x0)
        tp1, tgt = t.get("tp1"), t.get("tp2")
        tpl = t.get("tps") or []
        top = max([v for v in (tp1, tgt) if v] + [v for v, _, _ in tpl] or [e + side * R], key=lambda v: (v - e) * side)
        if not tp1 and not tgt and not is_open and t.get("exit") is not None and (t["exit"] - e) * side > R:
            top = t["exit"]                                   # trailing trades: green box to where it was closed
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=e, y1=s0, row=1, col=1, layer="below",
                      fillcolor="rgba(255,77,109,.16)", line=dict(color="rgba(255,77,109,.45)", width=1))
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=e, y1=top, row=1, col=1, layer="below",
                      fillcolor="rgba(0,229,192,.14)", line=dict(color="rgba(0,229,192,.45)", width=1))
        fig.add_shape(type="line", x0=x0, x1=x1, y0=e, y1=e, row=1, col=1, line=dict(color="#c9d6e8", width=1.2))
        for v in [tp1] + [v for v, _, _ in tpl]:
            if v:
                fig.add_shape(type="line", x0=x0, x1=x1, y0=v, y1=v, row=1, col=1, line=dict(color=UP, width=1, dash="dash"))
        fig.add_trace(go.Scatter(x=[x0], y=[e], mode="markers+text", showlegend=False,
                                 marker=dict(symbol="triangle-up" if buy else "triangle-down", size=14, color=col,
                                             line=dict(width=1, color="#04070d")),
                                 text=[f"{T('BUY') if buy else T('SELL')} {r:+.1f}R {mark}"],
                                 textposition="bottom center" if buy else "top center",
                                 textfont=dict(size=10, color=col, family="JetBrains Mono"),
                                 hovertext=f"{STRAT_LABEL.get(STRAT, '')} · {T(t.get('tier') or '')} · {r:+.2f}R",
                                 hoverinfo="text"), row=1, col=1)
        px, py = zip(*t["path"])
        fig.add_trace(go.Scatter(x=[x + sh for x in px], y=list(py), mode="lines", line=dict(color=hud.AMBER, width=1.2, shape="hv"),
                                 showlegend=False, hoverinfo="skip", opacity=0.85), row=1, col=1)
        if not is_open and t.get("exit_time") is not None:
            fig.add_trace(go.Scatter(x=[t["exit_time"] + sh], y=[t["exit"]], mode="markers", showlegend=False, hoverinfo="skip",
                                     marker=dict(symbol="x", size=8, color=hud.AMBER)), row=1, col=1)
        if k == len(shown) - 1:                              # price tags on the latest trade, TradingView style
            rr = lambda v: f"1:{abs(v - e) / R:.1f}" if R else ""
            tags = [(e, f"{T('Entry')} {fmt(e, D)}", "#c9d6e8"),
                    (s0, f"SL {fmt(s0, D)} (-1R)", DOWN)]
            if tpl:                                          # TP1-3 with the tested chance of reaching each
                for n_, ((v, lv, pct), ok) in enumerate(zip(tpl, t.get("tp_hit") or [False] * len(tpl)), 1):
                    tags.append((v, f"TP{n_} {fmt(v, D)} · +{abs(v - e) / inst.pip:.0f}p · " +
                                 (T("HIT") + " ✓" if ok else T("{p}% reach", p=pct)) +
                                 (" · " + T("close half, SL to breakeven") if n_ == 1 and tp1 else ""), UP))
                tags.append((t.get("target_now", tgt), f"{T('Exit (bounce)')} {fmt(t.get('target_now', tgt), D)}", hud.CYAN))
            hit = t.get("tp1_time") is not None
            tps = [] if tpl else sorted([(v, n) for v, n in ((tp1, T("SL moved to breakeven") if hit else T("close half, SL to breakeven")),
                                              (tgt, T("exit on the bounce"))) if v], key=lambda x: abs(x[0] - e))
            for n_, (v, note) in enumerate(tps, 1):                # TP1 = nearer level, TP2 = farther
                tags.append((v, f"TP{n_} {fmt(v, D)} ({rr(v)}) · {note}", UP))
            if is_open and not tp1 and not tgt:
                tags.append((t.get("stop_now", s0), f"{T('Trailing stop now')} {fmt(t.get('stop_now', s0), D)}", hud.AMBER))
            for y, txt, c in tags:
                fig.add_annotation(x=x1, y=y, text=txt, showarrow=False, xanchor="left", row=1, col=1,
                                   bgcolor="rgba(10,22,38,.92)", bordercolor=c, borderpad=3,
                                   font=dict(size=10, color=c, family="JetBrains Mono"))
    return {"n": len(shown), "won": won, "lost": lost, "total": total}


# ---------------------------------------------------------------- alerts

# The alert engine lives in the main page (not in the throw-away component frame), so the browser lets it play sound:
# the audio context is unlocked by the user's first click on the page and kept for the whole session.
ALERT_ENGINE = """<script>
(function () {
  const P = window.parent;
  if (P.ptAlertV === 2) return;                 // engine version: reinstall when it changes
  P.ptAlertV = 2;
  P.ptAudio = null;
  P.ptUnlock = function () {
    try { if (!P.ptAudio) P.ptAudio = new (P.AudioContext || P.webkitAudioContext)();
          if (P.ptAudio.state === "suspended") P.ptAudio.resume(); } catch (e) {}
  };
  P.document.addEventListener("click", P.ptUnlock, true);
  P.document.addEventListener("keydown", P.ptUnlock, true);
  P.ptBeep = function (kind, vol) {
    try {
      P.ptUnlock(); const c = P.ptAudio; if (!c) return "no-audio";
      const g0 = Math.min(1, Math.max(0.05, (vol || 8) / 10));
      const notes = kind === "sell" ? [880, 660, 440] : kind === "buy" ? [440, 660, 880] : [880, 660, 880];
      let t = c.currentTime;
      for (let round = 0; round < 3; round++) {            // 3 rounds of a 3-note alarm (~3 seconds)
        notes.forEach((f) => { const o = c.createOscillator(), g = c.createGain();
          o.type = "square"; o.frequency.value = f; g.gain.setValueAtTime(g0 * 0.6, t);
          g.gain.exponentialRampToValueAtTime(0.001, t + 0.25); o.connect(g); g.connect(c.destination);
          o.start(t); o.stop(t + 0.26); t += 0.28; });
        t += 0.25;
      }
      return c.state;
    } catch (e) { return "error"; }
  };
  P.ptBanner = function (title, body, kind) {
    const doc = P.document;
    let el = doc.getElementById("pt-alert-banner");
    if (!el) {
      const css = doc.createElement("style");
      css.textContent = "@keyframes ptpulse{0%,100%{opacity:1}50%{opacity:.55}}" +
        "#pt-alert-banner{position:fixed;left:0;right:0;top:0;z-index:999999;padding:28px 24px;text-align:center;" +
        "font-family:Orbitron,Inter,sans-serif;cursor:pointer;animation:ptpulse 1s ease-in-out infinite;" +
        "box-shadow:0 10px 60px rgba(0,0,0,.6)}#pt-alert-banner b{display:block;font-size:2.6rem;letter-spacing:.08em}" +
        "#pt-alert-banner span{display:block;font-family:Inter,sans-serif;font-size:1.15rem;margin-top:6px}" +
        "#pt-alert-banner small{display:block;margin-top:8px;opacity:.8;font-family:Inter,sans-serif}";
      doc.head.appendChild(css);
      el = doc.createElement("div"); el.id = "pt-alert-banner";
      el.onclick = function () { el.style.display = "none"; if (P.ptTitleTimer) { clearInterval(P.ptTitleTimer); doc.title = P.ptTitle0; } };
      doc.body.appendChild(el);
    }
    const bg = kind === "buy" ? "#00c9a7" : kind === "sell" ? "#ff4d6d" : "#00b8d9";
    el.style.background = bg; el.style.color = "#04070d"; el.style.display = "block";
    el.innerHTML = "<b>" + title + "</b><span>" + body + "</span><small>" + new Date().toLocaleTimeString() + " - click to close</small>";
    if (!P.ptTitle0) P.ptTitle0 = doc.title;
    if (P.ptTitleTimer) clearInterval(P.ptTitleTimer);
    let on = false;
    P.ptTitleTimer = setInterval(function () { on = !on; doc.title = on ? "🔔 " + title : P.ptTitle0; }, 800);
  };
  P.ptAlert = function (title, body, kind, vol) {
    const st = P.ptBeep(kind, vol);
    P.ptBanner(title, body, kind);
    try { if ("Notification" in P && P.Notification.permission === "granted")
            new P.Notification(title, { body: body, tag: "protrader-" + Date.now(), requireInteraction: true }); } catch (e) {}
    P.ptLastAlert = { title: title, body: body, audio: st, at: Date.now() };
  };
})();
</script>"""


def fire_alert(title, body, kind="info"):
    """Sound + desktop popup through the main-page alert engine."""
    if not sound:
        return
    components.html(ALERT_ENGINE + f"<script>window.parent.ptAlert({json.dumps(title)}, {json.dumps(body)}, {json.dumps(kind)}, {int(alert_vol)});</script>",
                    height=0)


def parse_alerts():
    out = []
    for part in (alert_txt or "").replace(";", ",").split(","):
        try:
            out.append(float(part.strip()))
        except ValueError:
            pass
    return out


def check_price_alerts(price):
    """Toast + beep when the last price crosses one of the user's levels since the previous refresh."""
    pk = f"lastpx-{symbol}"
    prev = st.session_state.get(pk)
    st.session_state[pk] = price
    if prev is None:
        return
    hit = [a for a in parse_alerts() if min(prev, price) <= a <= max(prev, price) and prev != price]
    for a in hit:
        msg = T("{sym} crossed {a} (now {p})", sym=symbol, a=fmt(a, D), p=fmt(price, D))
        st.toast(msg, icon="📍")
        fire_alert("ProTrader · " + symbol, msg)


def alert_new_setups(setups):
    """Toast (and beep) when an A/A+ setup appears that wasn't on the radar before."""
    sk = f"seen-{key}"
    ids = {(x.name, x.side, round(x.entry, max(0, D - 1))) for x in setups if x.grade in ("A+", "A")}
    if sk not in st.session_state:          # first look at this market: don't alert on what's already there
        st.session_state[sk] = ids
        return
    fresh = [x for x in setups if x.grade in ("A+", "A")
             and (x.name, x.side, round(x.entry, max(0, D - 1))) not in st.session_state[sk]]
    st.session_state[sk] |= ids
    for x in fresh:
        msg = T("New {g} {side} · {name} @ {e}", g=quality_word(x.grade), side=side_txt(x.side), name=setup_name(x.name), e=fmt(x.entry, D))
        st.toast(msg, icon="🔔")
        fire_alert("ProTrader · " + symbol, msg, "buy" if x.direction == 1 else "sell")


def alert_plan_events(P):
    """Alert on a new strategy entry and on a trade closed by the trailing stop."""
    if not P:
        return
    sk = f"plan-seen-{key}"
    state = {(str(t["time"]), t.get("exit_i") is None) for t in P["trades"]}
    tk = f"plan-tp1-{key}"
    tp1_now = {str(t["time"]) for t in P["trades"] if t.get("tp1_time") is not None}
    tp1_old = st.session_state.get(tk)
    st.session_state[tk] = tp1_now
    for tid in (tp1_now - tp1_old) if tp1_old is not None else ():
        msg = T("{sym} TP1 hit - close half and move the stop to breakeven", sym=symbol)
        st.toast(msg, icon="🎯")
        fire_alert("ProTrader · TP1 " + symbol, msg, "buy")
    if sk not in st.session_state:
        st.session_state[sk] = state
        return
    old = st.session_state[sk]
    st.session_state[sk] = state
    old_open = {t for t, o in old if o}
    for t in P["trades"]:
        tid = str(t["time"])
        is_open = t.get("exit_i") is None
        if all(tid != x for x, _ in old):
            side = T("BUY") if t["side"] == 1 else T("SELL")
            msg = T("{side} {sym} at {e} · stop {s} · {strat}", side=side, sym=symbol, e=fmt(t["entry"], D),
                    s=fmt(t["stop0"], D), strat=T(STRAT_LABEL.get(STRAT, "")))
            if t.get("tp1"):
                msg += f" · TP1 {fmt(t['tp1'], D)} · TP2 {fmt(t['tp2'], D)}"
            st.toast(msg, icon="🔔")
            fire_alert("ProTrader · " + side + " " + symbol, msg, "buy" if t["side"] == 1 else "sell")
        elif tid in old_open and not is_open:
            msg = T("{sym} trade closed by the trailing stop: {r}R", sym=symbol, r=f"{t['r']:+.2f}")
            st.toast(msg, icon="🏁")
            fire_alert("ProTrader · " + symbol, msg)


# ---------------------------------------------------------------- signal board (every tested plan, tier A and B)

@st.cache_data(ttl=300, show_spinner=False)
def board_results(source_, bucket):
    """plans.run_plan for every plan on closed candles; bucket changes every 5 minutes."""
    def get(sym, tf_):
        if sym in INSTRUMENTS:
            return closed_only(get_candles(sym, tf_, source_)[0], tf_)
        peer = get_peer(sym, tf_)
        return closed_only(peer, tf_) if peer is not None else None
    out = []
    for p in plans.PLANS:
        try:
            out.append(plans.run_plan(p, get))
        except Exception as e:  # noqa: BLE001 - one plan failing must not hide the others
            out.append({"plan": p, "error": str(e)})
    return out


def board_card(res):
    p = res["plan"]
    tier_col = UP if p["tier"] == "A" else hud.AMBER
    tag = (f"<span style='font-size:11px;padding:1px 7px;border-radius:9px;border:1px solid {tier_col};color:{tier_col}'>"
           f"{T('A · high accuracy') if p['tier'] == 'A' else T('B · trend trade')}</span>")
    head = f"<div style='display:flex;justify-content:space-between;gap:6px'><b>{p['sym']} · {T(p['name'])} ({p['tf']})</b>{tag}</div>"
    if "error" in res:
        return f"<div class='hud'>{head}<div class='bad'>{T('No data')}: {res['error'][:80]}</div></div>"
    inst_ = INSTRUMENTS[p["sym"]]
    f_ = lambda x: f"{x:,.{inst_.digits}f}"
    t = res["open"]
    s = res["stats"]
    foot = (f"<div class='txt muted' style='font-size:12px;margin-top:6px'>{T('Tested')}: {T('win')} {s['win']:.0f}% · PF {s['pf']:.2f} · "
            f"~{s['per_month']:.1f}/{T('month')}</div>" if s else "")
    if t:
        buy = t["side"] == 1
        col = UP if buy else DOWN
        lines = [f"{T('Entry')} <b>{f_(t['entry'])}</b> · {T('Stop now')} <b>{f_(t.get('stop_now', t['stop0']))}</b>"]
        for k, ((v, _, pct), hit) in enumerate(zip(t.get("tps") or [], t.get("tp_hit") or []), 1):
            lines.append(f"TP{k} <b>{f_(v)}</b> {'✓' if hit else f'({pct}%)'}" + (f" · {T('close half, SL to breakeven')}" if k == 1 else ""))
        if not t.get("tps"):
            lines.append(T("No fixed TP - trailing stop 3×ATR behind the best price"))
        lines.append(f"{T('Now')} {f_(res['price'])} · {t.get('open_r', 0):+.2f}R")
        body = (f"<div class='act' style='font-size:1.4rem;color:{col}'>{T('IN TRADE')} · {T('BUY') if buy else T('SELL')}</div>"
                + "".join(f"<div class='txt mono' style='font-size:13px'>{x}</div>" for x in lines))
    else:
        m = res["meter"]
        pct = round(100 * m["met"] / m["total"])
        bar = UP if m["ready"] else hud.AMBER if pct >= 60 else "#4a5a75"
        missing = [T(n) for n, ok, _ in m["items"] if not ok]
        body = (f"<div class='txt'>{T('WAIT')} · {T(m['side'])} {T('setup')} <b>{m['met']}/{m['total']}</b></div>"
                f"<div style='height:7px;background:#16233a;border-radius:5px;margin:5px 0'><div style='width:{pct}%;height:100%;"
                f"background:{bar};border-radius:5px'></div></div>"
                f"<div class='txt muted' style='font-size:12px'>{T('Waiting for')}: {', '.join(missing[:3]) or '-'}</div>")
    return f"<div class='hud' style='margin:0'>{head}{body}{foot}</div>"


REASONS = {
    "eur_a": ["EURUSD is in a clear trend (it is on one side of its 200-hour average)",
              "Price just made a sharp, extreme move against that trend - these usually snap back",
              "No news spike in the last 3 hours", "Not a break of the recent range (no new 30-candle low/high)",
              "Only the euro moved, not the whole US dollar (GBPUSD stayed calm)"],
    "eur_r3": ["EURUSD's hourly and daily trends point the same way",
               "RSI(2) moved against the trend 3 candles in a row to an extreme - a pullback inside the trend",
               "No news spike in the last 3 hours", "Not a break of the recent range",
               "Only the euro moved, not the whole US dollar (GBPUSD stayed calm)"],
    "gold_a": ["Gold is in an uptrend on both the hourly and the daily chart",
               "Price just made a deep, fast dip (RSI(2) under 2) - in an uptrend these usually bounce",
               "No news spike in the last 3 hours", "Not a break of the recent range",
               "Only gold moved, not the whole US dollar (EURUSD stayed calm)"],
    "gold_pull": ["Gold's daily trend is up (above its 50-day average) and the 4-hour trend agrees",
                  "On the hourly chart the fast average (EMA20) is above the slow one (EMA50): the trend is up",
                  "Price pulled back to EMA20 and closed back above it with a strong candle - the trend is resuming",
                  "Only during London / New York hours, when gold moves for real",
                  "No fixed target: the stop follows price up, so a big trend move can pay many times the risk"],
    "gold_pro": ["Gold's 4-hour and daily trends agree", "The market is trending (ADX at least 20) during active hours",
                 "Price pulled back to EMA20 and a confirmation candle closed in the trend direction",
                 "No fixed target: the stop follows price, so big moves are kept"],
}
REASONS["btc_brk"] = ["Bitcoin's daily trend and 4-hour trend point the same way",
                      "Price closed beyond its 7-day high (buy) or 7-day low (sell) - a breakout in the trend direction",
                      "Bitcoin and gold almost never move together, so this adds profit without adding the same risk",
                      "No fixed target: the stop follows price 4×ATR behind, so big crypto moves are kept"]
REASONS["gold_a15"] = REASONS["gold_a"]


def zones_card(S):
    """Buy / sell strength zones dashboard for the market on screen."""
    z = zones_mod.find_zones(closed_only(S["frames"][tf], tf))
    f_ = lambda v: f"{v:,.{D}f}"
    def zone_html(zz, side_z, col_z):
        if not zz:
            return f"<div class='txt muted'>{T('No active zone')}</div>"
        return (f"<div class='txt'><b style='color:{col_z}'>{T('BUY ZONE') if side_z == 'buy' else T('SELL ZONE')}</b> "
                f"<span class='mono'>{f_(zz['bottom'])} – {f_(zz['top'])}</span></div>"
                f"<div style='height:7px;background:#16233a;border-radius:5px;margin:4px 0'><div style='width:{zz['score']}%;height:100%;"
                f"background:{col_z};border-radius:5px'></div></div>"
                f"<div class='txt muted' style='font-size:12px'>{T('Strength')} {zz['score']}/99 · {T(zz['label'])} · "
                f"{zz['reactions']} {T('reactions')}</div>")
    near = (T("{side} zone, {d} ATR away", side=T(z["nearest"][0].upper()), d=f"{z['nearest'][1]:.1f}") if z.get("nearest") else "-")
    st.markdown(f"""<div class='hud' style='margin-top:10px'>
  <div class='hud-t'>{T('Strength zones')} · {symbol} {tf}</div>
  <div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px'>
    <div>{zone_html(z['sell'], 'sell', DOWN)}</div><div>{zone_html(z['buy'], 'buy', UP)}</div>
    <div class='txt'>{T('Trend')}: <b>{T(z['trend'])}</b><br>{T('Price')}: <b>{T(z['location'])}</b><br>{T('Nearest')}: <b>{near}</b></div>
  </div>
  <div class='txt muted' style='font-size:12px;margin-top:8px'>{T('Zones = places where price turned several times before. Tested 10 years: price reacted at them no more often than at random levels, so use them as a map and for targets, not as signals.')}</div>
</div>""", unsafe_allow_html=True)


CURVES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "plan_curves.json")


@st.cache_data(ttl=3600)
def _plan_curves(mtime):
    try:
        with open(CURVES_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def plan_curves():
    """The 10-year trade list of every plan; re-read whenever build_plan_stats.py rewrites the file."""
    return _plan_curves(os.path.getmtime(CURVES_PATH) if os.path.exists(CURVES_PATH) else 0)


def grow_account(trades, start_bal, risk):
    """Compound the balance trade by trade at a fixed % risk; returns (times, balances, worst drop %)."""
    bal, peak, dd, ts, bs = start_bal, start_bal, 0.0, [], []
    for t_, r_ in trades:
        bal *= 1 + risk / 100 * r_
        peak = max(peak, bal)
        dd = max(dd, 1 - bal / peak)
        ts.append(t_)
        bs.append(bal)
    return ts, bs, 100 * dd


def proof_card(res):
    """10-year test of the plans on the board, as YOUR balance at YOUR risk %: growth curve, yearly results, worst drop."""
    curves = plan_curves()
    ids = [r["plan"]["id"] for r in res if r["plan"]["id"] in curves]
    if not ids:
        return
    names = {r["plan"]["id"]: ("GOLD" if r["plan"]["sym"] == "XAUUSD" else r["plan"]["sym"]) + " · " + T(r["plan"]["name"]) +
             (" (M15)" if r["plan"]["tf"] == "M15" else "") for r in res}
    with st.expander("📈 " + T("10-year proof: what these signals would have done to your account"), expanded=False):
        pick = st.multiselect(T("Signals to include"), ids, default=ids, format_func=lambda k: names.get(k, k), key="proof_pick")
        if not pick:
            return
        tier = {r["plan"]["id"]: r["plan"]["tier"] for r in res}

        def _tested_mix():
            st.session_state["proof_rb"], st.session_state["proof_ra"] = 1.0, 2.0
        st.button(T("Use the tested mix: 1% on trend signals, 2% on high-accuracy signals"), on_click=_tested_mix, key="proof_mix",
                  help=T("In the 10-year tests this gave the best profit for the drawdown. More risk = more profit AND deeper drops."))
        c1, c2 = st.columns(2)
        risk_b = c1.slider(T("Risk on trend signals %"), 0.25, 3.0, float(risk_pct), 0.25, key="proof_rb",
                           help=T("Gold trend pullback: wins about 1 in 3, but the wins are big (trailing stop)."))
        risk_a = c2.slider(T("Risk on high-accuracy signals %"), 0.25, 4.0, float(risk_pct), 0.25, key="proof_ra",
                           help=T("Wins 83-91% of trades with small wins; in 10 years the worst run of losses was 1-4.4 risk units, so these can carry more risk."))
        rk = lambda k: risk_a if tier.get(k) == "A" else risk_b
        # scale each trade's R by its plan's risk, then compound at 1% per unit
        rows = sorted((pd.Timestamp(t_), float(r_) * rk(k)) for k in pick for t_, r_ in curves[k])
        ts, bs, dd = grow_account(rows, balance, 1.0)
        years = max(0.5, (ts[-1] - ts[0]).days / 365.25)
        cagr = (bs[-1] / balance) ** (1 / years) - 1
        by_year = pd.Series(bs, index=pd.DatetimeIndex(ts)).groupby(lambda t_: t_.year).last()
        prev = pd.concat([pd.Series([balance]), by_year.iloc[:-1]]).values
        yr_pct = 100 * (by_year.values / prev - 1)
        tiles = ((T("Start"), f"&#36;{balance:,.0f}", "#c9d6e8"), (T("After {y} years", y=f"{years:.0f}"), f"&#36;{bs[-1]:,.0f}", UP),
                 (T("Per year"), f"{100 * cagr:+.0f}%", UP if cagr >= 0 else DOWN), (T("Worst drop"), f"-{dd:.0f}%", DOWN))
        st.markdown("<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:6px 0 10px'>" +
                    "".join(f"<div style='background:#0a1626;border:1px solid #16233a;border-radius:10px;padding:8px 12px'>"
                            f"<div class='muted' style='font-size:12px'>{a_}</div><div class='mono' style='font-size:1.45rem;font-weight:700;"
                            f"color:{c_}'>{b_}</div></div>" for a_, b_, c_ in tiles) + "</div>", unsafe_allow_html=True)
        fig_ = go.Figure()
        fig_.add_trace(go.Scatter(x=ts, y=bs, mode="lines", line=dict(color=UP, width=2), name=T("All picked signals"),
                                  fill="tozeroy", fillcolor="rgba(0,229,192,.08)"))
        for k in pick:
            tk, bk, _ = grow_account([(pd.Timestamp(t_), float(r_)) for t_, r_ in curves[k]], balance, rk(k))
            fig_.add_trace(go.Scatter(x=tk, y=bk, mode="lines", line=dict(width=1), name=names.get(k, k), opacity=.75))
        fig_.update_layout(height=380, paper_bgcolor=BG, plot_bgcolor="rgba(4,10,20,.55)", margin=dict(l=0, r=10, t=10, b=0),
                           font=dict(color=MUTED, size=11), legend=dict(orientation="h", y=-0.15),
                           yaxis_type="log" if bs[-1] > 8 * balance else "linear")
        fig_.update_xaxes(gridcolor=GRID)
        fig_.update_yaxes(gridcolor=GRID, tickprefix="$")
        st.plotly_chart(fig_, use_container_width=True, config={"displayModeBar": False})
        # bad-luck check: the same trades in 500 random orders (drawn with replacement)
        rr = np.array([x for _, x in rows]) / 100
        sims = np.random.default_rng(11).choice(rr, size=(500, len(rr)), replace=True)
        eqs = np.cumprod(1 + sims, axis=1)
        dds = 1 - (eqs / np.maximum.accumulate(eqs, axis=1)).min(axis=1)
        lo, hi = np.percentile(eqs[:, -1] * balance, [5, 95])
        st.markdown(f"<div class='txt' style='margin:4px 0 8px'>🎲 {T('Bad-luck check (same trades, 500 random orders): in 1 case out of 20 the worst drop reaches {d}%; the ending balance lands between ${a} and ${b} in 9 cases out of 10.', d=f'{100 * np.percentile(dds, 95):.0f}', a=f'{lo:,.0f}', b=f'{hi:,.0f}')}</div>",
                    unsafe_allow_html=True)
        cells = "".join(f"<td style='text-align:center;padding:4px 6px;color:{UP if v >= 0 else DOWN}'><div class='muted' style='font-size:11px'>{y_}</div>"
                        f"<b class='mono'>{v:+.0f}%</b></td>" for y_, v in zip(by_year.index, yr_pct))
        st.markdown(f"<div style='overflow-x:auto'><table style='width:100%'><tr>{cells}</tr></table></div>", unsafe_allow_html=True)
        # the 0.01 minimum lot: below this balance the real risk is bigger than the slider says
        need = 0.0
        for r in res:
            k = r["plan"]["id"]
            last = next((t_ for t_ in reversed(r.get("trades") or []) if t_.get("stop0")), None)
            if k in pick and last:
                loss = abs(last["entry"] - last["stop0"]) * INSTRUMENTS[r["plan"]["sym"]].contract_size * 0.01
                need = max(need, loss / (rk(k) / 100))
        if need > balance:
            st.markdown(f"<div class='txt' style='color:{hud.AMBER};margin-top:6px'>⚠ " +
                        T("Your balance is below what the 0.01 minimum lot needs for this risk on every signal (about ${b}). "
                          "The real risk per trade will be higher than the sliders say.", b=f"{need:,.0f}") +
                        "</div>", unsafe_allow_html=True)
        st.markdown("<div class='txt muted' style='font-size:12px;margin-top:6px'>" +
                    T("Real 10-year history (Dukascopy prices, Pepperstone Razor costs), every closed trade of the picked signals, "
                      "the balance compounded at the risk % above. Change the Balance in the sidebar. This is a test of the "
                      "past, not a promise: real trading adds slippage, missed signals and emotions.") + "</div>", unsafe_allow_html=True)


def recent_card(res):
    """The latest signals of every plan on the live candles: when, side, entry, result in R and in $ at the sidebar risk."""
    rows = []
    for r in res:
        p = r["plan"]
        for t_ in (r.get("trades") or [])[-3:]:          # the last 3 of each plan, so busy plans don't hide the others
            rows.append((t_["time"], p, t_))
    if not rows:
        return
    rows.sort(key=lambda x: x[0], reverse=True)
    closed_r = [t_["r"] for _, _, t_ in rows if not t_.get("open")]
    usd = lambda r_: balance * risk_pct / 100 * r_
    html_ = ""
    for t0, p, t_ in rows:
        inst_ = INSTRUMENTS[p["sym"]]
        r_ = t_.get("open_r", t_["r"]) if t_.get("open") else t_["r"]
        col = UP if r_ > 0 else DOWN if r_ < 0 else MUTED
        side = (f"<b style='color:{UP if t_['side'] == 1 else DOWN}'>{T('BUY') if t_['side'] == 1 else T('SELL')}</b>")
        res_txt = (f"<b style='color:{col}'>{r_:+.2f}R</b> <span class='muted'>({'+' if r_ >= 0 else '-'}&#36;{abs(usd(r_)):,.2f})</span>"
                   + (f" <span style='color:{hud.AMBER}'>· {T('open')}</span>" if t_.get("open") else ""))
        html_ += (f"<tr><td class='muted mono' style='white-space:nowrap'>{t0 + pd.Timedelta(minutes=TIMEFRAMES[p['tf']][1]):%m-%d %H:%M}</td>"
                  f"<td>{'GOLD' if p['sym'] == 'XAUUSD' else p['sym']} · {T(p['name'])}</td><td>{side}</td>"
                  f"<td class='mono'>{t_['entry']:,.{inst_.digits}f}</td><td style='text-align:right;white-space:nowrap'>{res_txt}</td></tr>")
    won = sum(1 for x in closed_r if x > 0)
    summary = (T("Closed: {w} won, {l} lost, total {r}R ({u})", w=won, l=len(closed_r) - won, r=f"{sum(closed_r):+.2f}",
                 u=f"{'+' if sum(closed_r) >= 0 else '-'}${abs(usd(sum(closed_r))):,.2f}") if closed_r else "")
    with st.expander("🧾 " + T("Recent signals (live data) and how they ended"), expanded=False):
        st.markdown(f"<div style='overflow-x:auto'><table style='width:100%;font-size:13px'>{html_}</table></div>"
                    f"<div class='txt' style='margin-top:6px'>{summary}</div>"
                    f"<div class='txt muted' style='font-size:12px'>{T('Same rules as the live signals, on the candles loaded now (about the last 6 months). $ = your balance x risk % x R.')}</div>",
                    unsafe_allow_html=True)


def _years(s_):
    try:
        return round((pd.Timestamp(s_["to"]) - pd.Timestamp(s_["from"])).days / 365.25)
    except (KeyError, ValueError, TypeError):
        return 10


def simple_view(S=None):
    """One big card: the most profitable signal now (or the closest one) with plain reasons, then a short ranked list."""
    res = [r for r in board_results(source, int(time.time() // 300)) if "error" not in r]
    if not res:
        st.warning(T("No market data right now - try again in a minute."))
        return
    pm = lambda r: (r["stats"] or {}).get("avg_r", 0) * (r["stats"] or {}).get("per_month", 0)
    star = lambda r: "★★★" if pm(r) >= 0.8 else "★★☆" if pm(r) >= 0.3 else "★☆☆"
    res.sort(key=lambda r: (not r["open"], -pm(r)))
    live_ = [r for r in res if r["open"]]
    ready = lambda r: r["meter"]["met"] / r["meter"]["total"]
    near = [r for r in res if ready(r) >= 0.6]                   # most profitable among the ones that are getting close
    best = live_[0] if live_ else max(near or res, key=lambda r: (pm(r), ready(r)))
    p, s_, t = best["plan"], best["stats"] or {}, best["open"]
    inst_ = INSTRUMENTS[p["sym"]]
    f_ = lambda v: f"{v:,.{inst_.digits}f}"
    market = "GOLD" if p["sym"] == "XAUUSD" else p["sym"]
    ratio = abs(s_.get("avg_win", 0) / s_["avg_loss"]) if s_.get("avg_loss") else 0
    tested = (T("Tested {y} years: about +{m}% of your account a month at 1% risk per trade · wins {w}% of trades · "
                "the average win is {x}× the average loss", y=_years(s_), m=f"{pm(best):.1f}", w=f"{s_.get('win', 0):.0f}", x=f"{ratio:.1f}")
              if s_ else "")
    if t:
        buy = t["side"] == 1
        col = UP if buy else DOWN
        e, stop = t["entry"], t.get("stop_now", t["stop0"])
        ps = position_size(p["sym"], e, t["stop0"], balance, risk_pct, int(leverage), lot_size)
        lv = [(T("Entry"), f_(e)), (T("Stop loss"), f_(stop))]
        for k, ((v, _, pct), hit) in enumerate(zip(t.get("tps") or [], t.get("tp_hit") or []), 1):
            lv.append((f"TP{k}" + (" · " + T("close half") if k == 1 else ""), f_(v) + (" ✓" if hit else "")))
        if not t.get("tps"):
            lv.append((T("Target"), T("trailing stop - after each hourly candle, move your stop to the Stop loss shown here")))
        head = (f"<div class='act' style='font-size:2.3rem;color:{col};text-shadow:0 0 18px {col}66'>"
                f"{T('BUY') if buy else T('SELL')} {market}</div>"
                f"<div class='txt'>{T(p['name'])} · {T('signal since')} {t['time'] + pd.Timedelta(minutes=TIMEFRAMES[p['tf']][1]):%m-%d %H:%M} UTC · "
                f"{T('now')} {t.get('open_r', 0):+.2f}R</div>")
        levels = "".join(f"<div style='display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #16233a'>"
                         f"<span class='txt muted'>{a}</span><b class='mono'>{b}</b></div>" for a, b in lv)
        levels += (f"<div class='txt muted' style='margin-top:6px'>{ps['lots']:.2f} {T('lot')} · {T('risk')} &#36;{ps['risk_usd']:,.2f}"
                   f" ({ps['actual_risk_pct']}%)</div>")
        why_t = T("Why this signal")
    else:
        m = best["meter"]
        head = (f"<div class='act' style='font-size:2.1rem;color:{hud.AMBER}'>{T('WAIT')} · {T('no signal right now')}</div>"
                f"<div class='txt'>{T('Closest')}: <b>{market} · {T(p['name'])}</b> · {T(m['side'])} {T('setup')} {m['met']}/{m['total']}</div>")
        levels = (f"<div style='height:9px;background:#16233a;border-radius:6px;margin:10px 0'><div style='width:{round(100 * m['met'] / m['total'])}%;"
                  f"height:100%;background:{hud.AMBER};border-radius:6px'></div></div>"
                  + "".join(f"<div class='txt' style='padding:2px 0'>{'✅' if ok else '⏳'} {T(n)}"
                            f"{(' · <span class=muted>' + v + '</span>') if v else ''}</div>" for n, ok, v in m["items"]))
        why_t = T("How this signal works")
    reasons = "".join(f"<li class='txt' style='margin:3px 0'>{T(x)}</li>" for x in REASONS.get(p["id"], []))
    st.markdown(f"""<div class='hud verdict' style='padding:18px'>
  <div style='display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap'>
    <div class='hud-t'>{T('Most profitable signal')}</div><b style='color:{hud.AMBER}'>{T('Profit')} {star(best)}</b></div>
  {head}
  <div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px;margin-top:10px'>
    <div>{levels}</div>
    <div><div class='lbl'>{why_t}</div><ul style='margin:6px 0 0 18px;padding:0'>{reasons}</ul></div>
  </div>
  <div class='txt muted' style='margin-top:10px;font-size:12px'>{tested}</div>
</div>""", unsafe_allow_html=True)
    rows = ""
    for r in res:
        pr, mr = r["plan"], r["meter"]
        status = (f"<b style='color:{UP if r['open']['side'] == 1 else DOWN}'>{T('BUY') if r['open']['side'] == 1 else T('SELL')}</b>"
                  if r["open"] else f"{T('WAIT')} {mr['met']}/{mr['total']}")
        rows += (f"<tr><td style='color:{hud.AMBER}'>{star(r)}</td><td>{'GOLD' if pr['sym'] == 'XAUUSD' else pr['sym']} · {T(pr['name'])}</td>"
                 f"<td class='mono' style='text-align:right'>{status}</td></tr>")
    st.markdown(f"<div class='hud' style='margin-top:10px'><div class='hud-t'>{T('All signals · most profitable first')}</div>"
                f"<table style='width:100%;font-size:14px'>{rows}</table></div>", unsafe_allow_html=True)
    recent_card(res)
    proof_card(res)
    if S is not None and "Strength zones" in layers:
        zones_card(S)


def signal_board():
    res = board_results(source, int(time.time() // 300))
    cards = "".join(board_card(r) for r in res)
    st.markdown(f"<div class='hud-t' style='margin:6px 0'>{T('Signal board · every tested plan')}</div>"
                f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:10px'>{cards}</div>"
                f"<div class='txt muted' style='font-size:12px;margin:6px 0 10px'>"
                f"{T('A = high accuracy (83-91% win, small wins). B = trend trade (~40% win, trailing stop, bigger wins). The meter counts the conditions met now; a signal comes only at full.')}</div>",
                unsafe_allow_html=True)


# ---------------------------------------------------------------- live market panel

def market_panel():
    try:
        bk = (symbol, tf, source, int(time.time() // 20))          # full analysis at most every 20 s; price in between
        if st.session_state.get("_state_key") != bk:
            st.session_state["_state"] = build_state(symbol, tf, source)
            st.session_state["_state_key"] = bk
        S = dict(st.session_state["_state"])
        S["frames"] = dict(S["frames"])
    except Exception as e:  # noqa: BLE001
        st.error(T("Could not load market data: {e}", e=e))
        return
    a0, ctx = S["analyses"][0], S["ctx"]
    q = get_quote(symbol, source) if live else None
    if q:
        S["frames"][tf] = patch_live(S["frames"][tf], tf, q)
    live_px = float(S["frames"][tf]["close"].iloc[-1])
    prev = S["frames"][tf]["close"].iloc[-2]
    chg = (live_px / prev - 1) * 100
    now = pd.Timestamp.now(tz="UTC")
    cells = [("UTC / NY", f"{now:%H:%M} / {now.tz_convert('America/New_York'):%H:%M}")]
    sess, sstate = None, "na"
    if ctx is not None:
        q = ctx.session["quality"]
        sess = session_txt(ctx)
        sstate = "ok" if q == "prime" else "warn" if q == "active" or q.startswith("slow") else "bad"
        cells += [("ATR", f"{ctx.atr / inst.pip:.0f} {T('pips')}"), ("VWAP", fmt(ctx.vwap, D))]
    nxt = next((e for e in S["events"] if e["impact"] == "High" and e["time"] > now), None)
    if nxt:
        mins = int((nxt["time"] - now).total_seconds() // 60)
        cells.append((T("Next news"), (f"{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"{mins}m") + f" · {nxt['ccy']}"))
    cells.append((T("Today"), "STOP" if guard["blocked"] else f"{guard['trades']}/{max_trades} · {guard['pnl_pct']:+.1f}%"))
    labels = {"terminal": T("SCALPING TERMINAL"), "change": T("Change"), "session": T("Session"),
              "live": T("LIVE FEED"), "fallback": T("FALLBACK FEED")}
    st.markdown(hud.header(symbol, tf, fmt(live_px, D), chg, cells, "fallback" not in S["src"], sess, sstate, labels),
                unsafe_allow_html=True)
    check_price_alerts(live_px)
    if simple:
        simple_view(S)
        more = st.expander(T("Chart & full analysis"))
    else:
        signal_board()
        more = st.container()
    with more:

        if "fallback" in S["src"]:
            st.warning(T("TradingView feed unavailable - showing {src}. Prices can differ from Pepperstone; re-run Analyze when the feed is back.",
                         src=S["src"].split(" (")[0]))
        danger = newsmod.upcoming_high_impact(S["events"], 60)
        if danger:
            st.warning(T("High-impact news soon: ") + " · ".join(f"{e['time']:%H:%M} UTC {e['ccy']} {e['title']}" for e in danger))
        if guard["blocked"]:
            st.error(T("Risk guard: {why}. Signals are switched to WAIT for the rest of the day.", why=guard["why"]))
        if tf == "M5" and STRAT not in MR_TF:
            st.info(T("M5 failed the unseen-data test (it looked good on past data, then lost). Use it to watch price; take trades from M15."))
        if PLAN_MODE and STRAT:
            alert_plan_events(plan_state(symbol, tf, source, STRAT, S["frames"][tf].index[-1]))
        elif S["scalp"]:
            alert_new_setups(S["setups"])
        if test_alert:
            fire_alert("ProTrader · " + T("Test alert"), T("If you hear the alarm and see this banner, alerts work."))
            st.toast(T("Test alert sent - you should hear an alarm and see a big banner."), icon="🔔")

        sig = st.session_state.get(key)
        left, right = st.columns([2.35, 1], gap="medium")
        with left:
            st.plotly_chart(make_chart(S, sig), use_container_width=True, config=CHART_CONFIG)
            c_a, c_b = st.columns([1, 5])
            if c_a.button(T("Reset view"), key="reset_view", use_container_width=True):
                st.session_state["chart_rev"] = st.session_state.get("chart_rev", 0) + 1
                st.rerun(scope="fragment")
            c_b.caption(T("Drag to pan · mouse wheel to zoom · double-click chart to reset"))
        with right:
            if PLAN_MODE:
                P = plan_state(symbol, tf, source, STRAT, S["frames"][tf].index[-1]) if STRAT else None
                st.markdown(plan_verdict_html(sig, S, P), unsafe_allow_html=True)
            else:
                st.markdown(verdict_html(sig, S), unsafe_allow_html=True)

        g = gauges_html(S)
        cols = st.columns([1] * len(g) + [1.9], gap="small")
        for c, html in zip(cols, g):
            c.markdown(html, unsafe_allow_html=True)
        items = plan_checklist(S, P if PLAN_MODE else None) if PLAN_MODE else checklist_items(S, sig)
        cols[-1].markdown(hud.checklist(items, T("Pre-trade checklist · {ok}/{n} green")), unsafe_allow_html=True)

        board = get_board()
        if board:
            cells = "".join(f"<span>{x['name']} <b style='color:{UP if x['chg_24h'] >= 0 else DOWN}'>{x['chg_24h']:+.2f}%</b></span>"
                            for x in board)
            st.markdown(f"<div class='hud' style='margin-top:10px;padding:9px 16px'><div class='macro'>"
                        f"<span class='hud-t' style='margin:0'>{T('Macro 24h')}</span>{cells}</div></div>", unsafe_allow_html=True)

        if PLAN_MODE and STRAT and P and P["trades"]:
            st.markdown("##### " + T("Recent trades of this strategy"))
            rows_ = [{T("Time"): f"{t['time']:%m-%d %H:%M}", T("Side"): T("LONG" if t["side"] == 1 else "SHORT"),
                      T("Entry"): round(t["entry"], D), T("Initial stop"): round(t["stop0"], D),
                      T("Exit"): round(t["exit"], D) if t.get("exit") is not None else "⏳",
                      "R": round(t.get("open_r", t["r"]) if t.get("exit_i") is None else t["r"], 2)} for t in P["trades"][::-1][:12]]
            st.dataframe(pd.DataFrame(rows_), hide_index=True, use_container_width=True)
        if S["scalp"] and not PLAN_MODE:
            st.markdown("##### " + T("Setup radar"))
            if S["setups"]:
                rad = pd.DataFrame(as_dicts(S["setups"]))[["grade", "side", "name", "order_type", "entry", "stop", "tp1", "tp2", "rr_tp2", "trigger"]]
                rad["grade"] = rad["grade"].map(quality_word)
                rad.insert(3, "edge", [edge_txt(getattr(x, "edge", None)) for x in S["setups"]])
                rad.insert(4, "similar", [similar_txt(getattr(x, "quality", None)) for x in S["setups"]])
                rad["side"] = rad["side"].map(side_txt)
                rad["name"] = rad["name"].map(setup_name)
                rad["order_type"] = rad["order_type"].map(order_txt)
                rad.columns = [T("Quality"), T("Side"), T("Setup"), T("Backtest"), T("Similar past setups"), T("Order"), T("Entry"), T("Stop"), "TP1", "TP2",
                               "R (TP2)", T("Trigger")]
                st.dataframe(rad, hide_index=True, use_container_width=True,
                             column_config={T("Trigger"): st.column_config.TextColumn(width="large")})
            else:
                st.caption(T("Nothing clean right now. No sweep, no VWAP retest, no fresh break. Waiting is a position."))


# ---------------------------------------------------------------- analyze (AI) on demand
# (placed after all helper functions so the strategy/plan helpers exist when the button is pressed)

if run:
    try:
        t0 = time.time()
        with st.status(T("Analyzing…"), expanded=True) as status:
            st.write("① " + T("Loading market data and running the engine"))
            S = build_state(symbol, tf, source)
            sym_news = newsmod.relevant_news(get_news(), symbol)
            if PLAN_MODE:
                P = plan_state(symbol, tf, source, STRAT, S["frames"][tf].index[-1]) if STRAT else None
                sig = plan_base_signal(P)
            else:
                sig = scalp_rule_signal(S["ctx"], S["setups"]) if S["scalp"] else rule_based_signal(symbol, S["analyses"])
            if PLAN_MODE and use_ai and provider_key(provider):
                st.write("② " + T("DeepSeek is reading the market ({m})…", m=model))
                try:
                    news_txt = newsmod.news_prompt_text(sym_news, S["events"]) + "\n\n" + macro.board_text(get_board())
                    ai = ai_signal(symbol, tf, S["analyses"], news_txt, provider, model,
                                   scalp_text=plan_prompt_text(P), scalp_atr=S["ctx"].atr if S["ctx"] else None,
                                   lang=i18n.lang(), lessons_text=lessons_mod.prompt_text(current_lessons(), symbol, tf),
                                   plan_mode=True)
                    for k_ in ("summary", "technical_view", "fundamental_view", "risks", "scenarios", "management", "invalidation"):
                        if ai.get(k_):
                            sig[k_] = ai[k_]
                    sig["ai_decision"] = ai.get("decision")
                    sig["engine"] = ai.get("engine", sig.get("engine"))
                except Exception as e:  # noqa: BLE001
                    sig.setdefault("warnings", []).append(T("AI unavailable ({e}) - rule engine shown.", e=str(e)[:120]))
            elif use_ai and provider_key(provider):
                st.write("② " + T("DeepSeek is reading the market ({m})…", m=model))
                try:
                    news_txt = newsmod.news_prompt_text(sym_news, S["events"]) + "\n\n" + macro.board_text(get_board())
                    ai = ai_signal(symbol, tf, S["analyses"], news_txt,
                                   provider, model,
                                   scalp_text=context_text(S["ctx"], S["setups"][:4]) if S["scalp"] else "",
                                   scalp_atr=S["ctx"].atr if S["scalp"] else None, lang=i18n.lang(),
                                   lessons_text=lessons_mod.prompt_text(current_lessons(), symbol, tf))
                    sig = merge_signals(ai, sig, S["analyses"][0].price, S["ctx"].atr if S["scalp"] else S["analyses"][0].atr)
                except Exception as e:  # noqa: BLE001
                    sig.setdefault("warnings", []).append(T("AI unavailable ({e}) - rule engine shown.", e=str(e)[:120]))
            if S["scalp"] and not PLAN_MODE:
                # the chosen setup can't be graded above what its backtest supports (AI included)
                cap, why = bt.evidence_cap(edge_for(get_backtest(symbol, tf)[0], sig.get("setup")))
                capped = bt.cap_grade(sig.get("grade", "C"), cap)
                if capped != sig.get("grade"):
                    sig["grade"] = capped
                    sig.setdefault("warnings", []).append(T("Grade capped to {g}: {why}.", g=capped, why=tr_dyn(why)))
                if capped not in ("A+", "A") and sig.get("decision") in ("LONG", "SHORT"):
                    sig["decision"] = "NO_TRADE"
            if guard["blocked"] and sig.get("decision") in ("LONG", "SHORT"):
                sig["decision"] = "NO_TRADE"
                sig.setdefault("warnings", []).append(T("Risk guard: {why} - no new trades today.", why=guard["why"]))
            sig["lang"] = i18n.lang()
            sig["created"] = pd.Timestamp.now(tz="UTC")
            sig["price_at_signal"] = S["analyses"][0].price
            st.session_state[key] = sig
            if not PLAN_MODE:
                journal.log_signal(symbol, tf, sig)
            status.update(label=T("Done in {s} s", s=f"{time.time() - t0:.0f}"), state="complete", expanded=False)
    except Exception as e:  # noqa: BLE001
        st.error(T("Could not analyze: {e}", e=e))


st.fragment(run_every=live_every if live else None)(market_panel)()

# ---------------------------------------------------------------- detail tabs

sig = st.session_state.get(key)
_tabs_box = st.expander(T("More tools · Time Machine, news, backtest, journal")) if simple else st
t_an, t_tm, t_orb, t_ctx, t_news, t_bt, t_scan, t_j = _tabs_box.tabs([T("Analysis"), T("Time Machine"), T("Opening range"),
                                                                       T("Market structure"),
                                                         T("News & calendar"), T("Backtest"), T("Scanner"), T("Journal")])

def fan_chart(candles, res_, side_, entry_, stop_, target_, bar_min, digits):
    """Real candles, then the replay paths fanning out from the entry, with stop / entry / target lines."""
    fmt_ = lambda v: f"{v:,.{digits}f}"
    fig_ = go.Figure(go.Candlestick(x=candles.index, open=candles.open, high=candles.high, low=candles.low, close=candles.close,
                                    increasing=dict(line=dict(color=UP, width=1), fillcolor=UP),
                                    decreasing=dict(line=dict(color=DOWN, width=1), fillcolor=DOWN), showlegend=False))
    t0 = candles.index[-1]
    xs = [t0 + pd.Timedelta(minutes=bar_min * (k + 1)) for k in range(res_["paths"].shape[1])]
    for p_ in res_["paths"]:
        fig_.add_trace(go.Scatter(x=[t0] + xs, y=[entry_] + list(p_), mode="lines", hoverinfo="skip", showlegend=False,
                                  line=dict(width=0.7, color="rgba(77,140,255,.28)")))
    for lvl, nm, col_ in ((stop_, "Stop", DOWN), (entry_, "Entry", "#c9d6e8"), (target_, "Target", UP)):
        fig_.add_hline(y=lvl, line=dict(color=col_, dash="dash", width=1.2),
                       annotation_text=f"{T(nm)} {fmt_(lvl)}", annotation_position="right", annotation_font=dict(color=col_, size=11))
    fig_.update_layout(height=430, paper_bgcolor=BG, plot_bgcolor="rgba(4,10,20,.55)", margin=dict(l=0, r=90, t=10, b=0),
                       font=dict(color=MUTED, size=11), xaxis_rangeslider_visible=False)
    fig_.update_xaxes(gridcolor=GRID)
    fig_.update_yaxes(gridcolor=GRID, side="right", tickformat=f".{digits}f")
    return fig_


def outcome_bars(res_):
    """'How the replays end' bars, like the video."""
    rows_ = [(T("Target first"), res_["target_first"], UP), (T("Stop first"), res_["stop_first"], DOWN),
             (T("Neither in time"), res_["neither"], "#8b949e")]
    html_ = "".join(f"<div style='display:flex;align-items:center;gap:10px;margin:6px 0'><span class='txt' style='width:130px'>{n}</span>"
                    f"<div style='flex:1;background:#16233a;border-radius:4px'><div style='width:{100 * v:.1f}%;background:{c};height:22px;"
                    f"border-radius:4px'></div></div><b class='mono' style='width:60px;text-align:right'>{100 * v:.1f}%</b></div>"
                    for n, v, c in rows_)
    return (f"<div class='hud'><div class='hud-t'>{T('How the 10,000 replays end')}</div>{html_}"
            f"<div class='txt muted' style='margin-top:6px'>{T('Average result')}: <b>{res_['avg_r']:+.2f}R</b> · "
            f"{T('risk:reward')} 1:{res_['rr']:.2f}</div></div>")


with t_orb:
    st.markdown(f"<div class='hud-t'>{T('Opening-range breakout · watch the open')}</div>", unsafe_allow_html=True)
    o1, o2, o3 = st.columns(3)
    orb_sym = o1.segmented_control(T("Market"), ["XAUUSD", "EURUSD"], default="XAUUSD", key="orb_sym") or "XAUUSD"
    orb_sess = o2.segmented_control(T("Session"), ["London", "New York"], default="New York", key="orb_sess") or "New York"
    orb_min = o3.segmented_control(T("Range"), [15, 30], default=15, format_func=lambda m: f"{m} min", key="orb_min") or 15
    orb_inst = INSTRUMENTS[orb_sym]
    orb_m5 = get_candles(orb_sym, "M5", source)[0]
    orb = orb_tool.opening_range(orb_m5, orb_sess, orb_min)
    if not orb:
        st.info(T("No session data yet."))
    else:
        f_o = lambda v: f"{v:,.{orb_inst.digits}f}"
        tzs = orb["start"].tzname()
        rule = (T("Close above") if orb["side"] >= 0 else T("Close below"))
        timer = T(orb["status"]) + (f" · {orb['break_time']:%H:%M} {tzs}" if orb["break_time"] is not None else
                                    f" · {T('since')} {orb['end']:%H:%M} {tzs}")
        cards = [(T("Opening range high"), f_o(orb["high"]), f"{orb['start']:%H:%M} – {orb['end']:%H:%M} {tzs} · {T('low')} {f_o(orb['low'])}", "#c9d6e8"),
                 (T("Entry rule"), rule, T("the range high (buy) or low (sell), 5-min candle close"), hud.AMBER),
                 (T("Entry timer"), timer, f"{orb_sym} · {T(orb_sess)} {T('open')}", UP if orb["side"] == 1 else DOWN if orb["side"] == -1 else hud.CYAN)]
        st.markdown("<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px'>" + "".join(
            f"<div class='hud' style='margin:0;border-top:3px solid {c}'><div class='txt muted'>{a}</div>"
            f"<div class='act mono' style='font-size:1.6rem'>{b}</div><div class='txt muted' style='font-size:12px'>{n}</div></div>"
            for a, b, n, c in cards) + "</div>", unsafe_allow_html=True)
        dc = orb["day_candles"]
        fig_o = go.Figure(go.Candlestick(x=dc.index, open=dc.open, high=dc.high, low=dc.low, close=dc.close, showlegend=False,
                                         increasing=dict(line=dict(color=UP, width=1), fillcolor=UP),
                                         decreasing=dict(line=dict(color=DOWN, width=1), fillcolor=DOWN)))
        fig_o.add_shape(type="rect", x0=orb["start"], x1=orb["end"], y0=orb["low"], y1=orb["high"],
                        fillcolor="rgba(77,140,255,.18)", line=dict(color="rgba(77,140,255,.7)", width=1))
        fig_o.add_hline(y=orb["high"], line=dict(color="#4d8cff", dash="dot"), annotation_text=f"{T('Range high')} {f_o(orb['high'])}")
        fig_o.add_hline(y=orb["low"], line=dict(color="#4d8cff", dash="dot"), annotation_text=f"{T('Range low')} {f_o(orb['low'])}",
                        annotation_position="bottom right")
        if orb["break_time"] is not None:
            fig_o.add_trace(go.Scatter(x=[orb["break_time"]], y=[orb["entry"]], mode="markers+text", showlegend=False,
                                       marker=dict(symbol="triangle-up" if orb["side"] == 1 else "triangle-down", size=14,
                                                   color=UP if orb["side"] == 1 else DOWN),
                                       text=[T("BUY") if orb["side"] == 1 else T("SELL")], textposition="bottom center"))
        fig_o.update_layout(height=380, paper_bgcolor=BG, plot_bgcolor="rgba(4,10,20,.55)", margin=dict(l=0, r=10, t=10, b=0),
                            font=dict(color=MUTED, size=11), xaxis_rangeslider_visible=False)
        fig_o.update_xaxes(gridcolor=GRID)
        fig_o.update_yaxes(gridcolor=GRID, side="right", tickformat=f".{orb_inst.digits}f")
        st.plotly_chart(fig_o, use_container_width=True)
        if orb["side"]:
            rr_o = st.select_slider(T("Target"), [1.0, 1.5, 2.0, 3.0], value=1.0, format_func=lambda v: f"{v:g}R", key="orb_rr")
            R_o = abs(orb["entry"] - orb["stop"])
            tgt_o = orb["entry"] + orb["side"] * rr_o * R_o
            if st.button(T("Replay this breakout 10,000×"), type="primary", key="orb_run"):
                hist_o = closed_only(orb_m5, "M5")
                upto = hist_o[hist_o.index <= orb["break_time"]]
                res_o = timemachine.simulate(upto, orb["side"], orb["entry"], orb["stop"], tgt_o,
                                             horizon_bars=orb_tool.SESSION_HOURS * 12, lookback_bars=1500, block=6)
                st.plotly_chart(fan_chart(upto.tail(40), res_o, orb["side"], orb["entry"], orb["stop"], tgt_o, 5, orb_inst.digits),
                                use_container_width=True)
                st.markdown(outcome_bars(res_o), unsafe_allow_html=True)
        st.caption(T("Tested on 2 years of gold and EURUSD with costs: this breakout broke even or lost (profit factor 0.76-1.02). "
                     "Use it to watch the open, not as a signal on its own."))

with t_tm:
    st.markdown(f"<div class='hud-t'>{T('Time Machine · replay a trade 10,000 times')}</div>", unsafe_allow_html=True)
    st.caption(T("Each replay strings together random blocks of this market's real recent 15-minute candles, starting at your "
                 "entry. It shows how wide the outcomes are - not which one will happen. The tested plan numbers are more reliable."))
    tm_sym = st.segmented_control(T("Market"), ["EURUSD", "XAUUSD"], default=symbol if symbol in ("EURUSD", "XAUUSD") else "EURUSD",
                                  key="tm_sym") or "EURUSD"
    tm_inst = INSTRUMENTS[tm_sym]
    tm_c = closed_only(get_candles(tm_sym, "M15", source)[0], "M15")
    tm_px = float(tm_c.close.iloc[-1])
    tm_atr = float(add_indicators(tm_c).atr.iloc[-1])
    tm_open = next((r["open"] for r in board_results(source, int(time.time() // 300))
                    if r.get("open") and r["plan"]["sym"] == tm_sym), None)
    if tm_open:
        st.info(T("Prefilled with the open {sym} trade from the signal board.", sym=tm_sym))
        d_side, d_e, d_s = tm_open["side"], tm_open["entry"], tm_open.get("stop_now", tm_open["stop0"])
        d_t = (tm_open.get("tps") or [(tm_open["entry"] + tm_open["side"] * 2 * abs(tm_open["entry"] - tm_open["stop0"]), 0, 0)])[0][0]
    else:
        d_side, d_e = 1, tm_px
        d_s, d_t = tm_px - 1.5 * tm_atr, tm_px + 2.0 * tm_atr
    step_ = 10 ** -tm_inst.digits
    c1, c2, c3, c4 = st.columns(4)
    tm_side = 1 if c1.segmented_control(T("Direction"), [T("BUY"), T("SELL")], default=T("BUY") if d_side == 1 else T("SELL"),
                                        key="tm_side") == T("BUY") else -1
    tm_e = c2.number_input(T("Entry"), value=float(round(d_e, tm_inst.digits)), step=step_ * 10, format=f"%.{tm_inst.digits}f", key="tm_e")
    tm_s = c3.number_input(T("Stop loss"), value=float(round(d_s, tm_inst.digits)), step=step_ * 10, format=f"%.{tm_inst.digits}f", key="tm_s")
    tm_t = c4.number_input(T("Target"), value=float(round(d_t, tm_inst.digits)), step=step_ * 10, format=f"%.{tm_inst.digits}f", key="tm_t")
    tm_h = st.slider(T("Hours to replay"), 1, 48, 8, key="tm_h")
    ok_geom = (tm_s < tm_e < tm_t) if tm_side == 1 else (tm_t < tm_e < tm_s)
    if not ok_geom:
        st.warning(T("For a buy the stop must be below the entry and the target above it (the other way round for a sell)."))
    elif st.button(T("Run 10,000 replays"), type="primary", key="tm_run"):
        res_ = timemachine.simulate(tm_c, tm_side, tm_e, tm_s, tm_t, horizon_bars=tm_h * 4)
        st.plotly_chart(fan_chart(tm_c.tail(48), res_, tm_side, tm_e, tm_s, tm_t, 15, tm_inst.digits), use_container_width=True)
        ob_, hist_ = st.columns([1, 1])
        ob_.markdown(outcome_bars(res_), unsafe_allow_html=True)
        fig_h = go.Figure(go.Histogram(x=res_["closes"], nbinsx=40, marker_color="rgba(255,140,90,.8)", showlegend=False))
        for lvl, col_ in ((tm_s, DOWN), (tm_e, "#c9d6e8"), (tm_t, UP)):
            fig_h.add_vline(x=lvl, line=dict(color=col_, dash="dash", width=1.2))
        fig_h.update_layout(height=230, paper_bgcolor=BG, plot_bgcolor="rgba(4,10,20,.55)", margin=dict(l=0, r=10, t=30, b=0),
                            font=dict(color=MUTED, size=11), title=dict(text=T("Where price ends"), font=dict(size=12)))
        hist_.plotly_chart(fig_h, use_container_width=True)
        st.caption(T("Risk:reward 1:{rr}. A high 'target first' with a far stop can still lose money on average - check the average result.",
                     rr=f"{res_['rr']:.2f}"))


def perf_card(title, r):
    """HUD performance card from a series of R results."""
    r = pd.Series(r, dtype=float)
    pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum())
    return hud.stats_card(title, r.cumsum().round(3).tolist(), float((r > 0).mean() * 100), float(r.mean()), float(pf), len(r),
                          {"win": T("Win rate"), "avg": T("Avg R / trade"), "pf": T("profit factor"), "trades": T("trades")})


def tr_cols(df):
    """Translate summarize() column names."""
    return df.rename(columns={c: T(c) for c in df.columns}) if df is not None and not df.empty else df

with t_an:
    learned = current_lessons()
    if learned:
        with st.expander("🧠 " + T("What the app has learned on {sym} {tf}", sym=symbol, tf=tf), expanded=False):
            for x in learned:
                st.caption("• " + x)
            st.caption(T("These measured lessons are sent to DeepSeek with every analysis."))
    if not sig:
        st.caption(T("Run Analyze to see the reasoning."))
    else:
        st.markdown(f"**{sig.get('summary', '')}**")
        for w in sig.get("warnings", []):
            st.caption(f"⚠ {tr_dyn(w)}")
        c1, c2 = st.columns(2)
        c1.markdown(f"**{T('Technical read')}**")
        c1.write(sig.get("technical_view", ""))
        c2.markdown(f"**{T('News & macro')}**")
        c2.write(sig.get("fundamental_view", ""))
        if sig.get("scenarios"):
            st.markdown(f"**{T('Scenarios (next 1-2 h)')}**")
            cols = st.columns(len(sig["scenarios"]))
            for col, sc in zip(cols, sig["scenarios"]):
                col.markdown(f"{sc.get('name')} · **{sc.get('probability')}%**")
                col.caption(f"{sc.get('trigger', '')} — {sc.get('description', '')}")
        if sig.get("risks"):
            st.markdown(f"**{T('Risks')}**")
            for r in as_list(sig["risks"]):
                st.caption(f"• {r}")
        if sig.get("model_reasoning"):
            with st.expander(T("Model reasoning")):
                st.text(sig["model_reasoning"][:20000])

with t_ctx:
    try:
        S2 = build_state(symbol, tf, source)
        cols = st.columns(len(S2["analyses"]))
        for col, a in zip(cols, S2["analyses"]):
            with col:
                st.markdown(f"**{a.tf}** · {T('score')} {a.score:+.0f} · {a.structure}")
                st.dataframe(pd.DataFrame(a.signals.items(), columns=[T("Indicator"), T("Reading")]),
                             hide_index=True, use_container_width=True)
                st.caption("S: " + ", ".join(fmt(z["price"], D) for z in a.supports) +
                           "  ·  R: " + ", ".join(fmt(z["price"], D) for z in a.resistances))
        if S2["ctx"] is not None:
            ctx = S2["ctx"]
            st.markdown(f"**{T('Structure log (execution timeframe)')}**")
            st.caption(" → ".join(f"{e['time']:%H:%M} {e['type']} {'↑' if e['dir'] == 1 else '↓'} {fmt(e['level'], D)}"
                                  for e in ctx.events[-8:]) or "—")
            st.markdown(f"**{T('Key levels')}**")
            st.caption(" · ".join(f"{k} {fmt(v, D)}" for k, v in ctx.levels.items()))
        daily, _ = get_candles(symbol, "D1", source)
        st.markdown(f"**{T('Daily pivots')}**")
        st.caption(" · ".join(f"{k} {fmt(v, D)}" for k, v in pivots(daily).items()))
    except Exception as e:  # noqa: BLE001
        st.caption(T("Unavailable: {e}", e=e))

with t_news:
    sym_news = newsmod.relevant_news(get_news(), symbol)
    events = newsmod.relevant_events(get_calendar(), symbol)
    l, r = st.columns([1.4, 1])
    with l:
        if not sym_news:
            st.caption(T("No relevant headlines fetched."))
        for n in sym_news:
            dot = {"HIGH": DOWN, "MEDIUM": "#e3b341", "LOW": MUTED}[n["impact"]]
            t = f"{n['time']:%d %b %H:%M}" if n["time"] else ""
            st.markdown(f"<span style='color:{dot}'>●</span> <a href='{n['link']}' style='color:#c5ccd6;text-decoration:none'>"
                        f"{n['title']}</a><br><span class='small'>{n['source']} · {t} UTC</span>", unsafe_allow_html=True)
    with r:
        if events:
            st.dataframe(pd.DataFrame([{"UTC": f"{e['time']:%a %H:%M}", T("Ccy"): e["ccy"], T("Impact"): e["impact"],
                                        T("Event"): e["title"], T("Fcst"): e["forecast"], T("Prev"): e["previous"],
                                        T("Actual"): e.get("actual", "")} for e in events]),
                         hide_index=True, use_container_width=True, height=520)
        else:
            st.caption(T("Calendar unavailable."))

with t_bt:
    if tf not in ("M5", "M15"):
        st.caption(T("Backtest covers the scalping setups (M5 / M15)."))
    else:
        trades, meta = get_backtest(symbol, tf)
        c1, c2 = st.columns([1, 3])
        run_bt = c1.button(T("Run backtest"), help=T("Replays ~5,000 bars bar-by-bar. Takes 1-3 minutes."))
        if meta and meta.get("outdated"):
            c2.warning(T("Engine settings changed since the last run - these stats no longer apply. Run the backtest again."))
        elif meta:
            age_h = (time.time() - meta.get("saved", 0)) / 3600
            c2.caption(T("{sym} {tf} · {bars} bars · {a} → {b} UTC · updated {h} h ago. Walk-forward, no look-ahead, spread included; half off at TP1, stop to break-even, rest to TP2, flat after 3 h.",
                         sym=symbol, tf=tf, bars=meta.get("bars"), a=meta.get("start", "")[:16], b=meta.get("end", "")[:16],
                         h=f"{age_h:.1f}"))
        else:
            c2.caption(T("No backtest yet for this market. Run it once; results are saved and reused."))
        if run_bt:
            prog = st.progress(0.0, text=T("Replaying history…"))
            try:
                hist = load_ohlc(symbol, tf, 5000, source)
                dly, _ = get_candles(symbol, "D1", source)
                inter = load_intermarket(symbol, tf, 5000)
                res = bt.run_backtest(hist, symbol, TIMEFRAMES[tf][1], daily=dly, inter=inter,
                                      progress=lambda x: prog.progress(min(1.0, x), text=f"{T('Replaying history…')} {x * 100:.0f}%"))
                bt.save(symbol, tf, res, {"bars": len(hist), "start": str(hist.index[0]), "end": str(hist.index[-1])})
                get_backtest.clear()
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(T("Backtest failed: {e}", e=e))
        if trades is not None and not trades.empty:
            f = trades[trades["filled"]].sort_values("time")
            if not f.empty:
                st.markdown(perf_card(T("Backtest performance") + f" · {symbol} {tf}", f["r"]), unsafe_allow_html=True)
            a, b = st.columns(2)
            by_setup = bt.summarize(trades, "setup")
            if not by_setup.empty:
                by_setup.index = [setup_name(i) for i in by_setup.index]
            by_side = bt.summarize(trades, "side")
            if not by_side.empty:
                by_side.index = [side_txt(i) for i in by_side.index]
            by_sess = bt.summarize(trades, "session")
            if not by_sess.empty:
                by_sess.index = [quality_txt(i) for i in by_sess.index]
            a.markdown(f"**{T('By setup')}**")
            a.dataframe(tr_cols(by_setup), use_container_width=True)
            b.markdown(f"**{T('By grade')}**")
            b.dataframe(tr_cols(bt.summarize(trades, "grade")), use_container_width=True)
            a.markdown(f"**{T('By session')}**")
            a.dataframe(tr_cols(by_sess), use_container_width=True)
            b.markdown(f"**{T('By side')}**")
            b.dataframe(tr_cols(by_side), use_container_width=True)
            if "hour" in trades:
                hs = bt.summarize(trades, "hour").sort_index()
                if not hs.empty:
                    st.markdown(f"**{T('By hour of day (UTC) - weak hours lower the grade live')}**")
                    hb = go.Figure(go.Bar(x=[f"{int(h):02d}" for h in hs.index], y=hs["avg R"],
                                          marker_color=[UP if v > 0 else DOWN for v in hs["avg R"]],
                                          text=hs["trades"], hovertemplate="%{x}:00 UTC<br>avg %{y:+.2f}R<br>%{text} trades"))
                    hb.update_layout(height=220, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor=BG, plot_bgcolor=BG,
                                     font=dict(color=MUTED, size=11), yaxis=dict(title="avg R", gridcolor=GRID))
                    st.plotly_chart(hb, use_container_width=True, config={"displaylogo": False})
            days = (trades["time"].max() - trades["time"].min()).days
            st.caption(T("Past results over ~{d} days. Small samples are noisy; treat this as evidence, not a promise.", d=days))

with t_scan:
    st.caption(T("Best rule-engine setup on {tf} for every instrument. No AI cost.", tf=tf))
    if st.button(T("Scan all instruments")):
        rows = []
        for s in INSTRUMENTS:
            try:
                Sx = build_state(s, tf, source)
                if Sx["scalp"] and Sx["setups"]:
                    b = Sx["setups"][0]
                    rows.append({T("Symbol"): s, T("Grade"): b.grade, T("Side"): side_txt(b.side), T("Setup"): setup_name(b.name),
                                 T("Entry"): b.entry, "R (TP2)": round(b.rr(b.tp2), 1),
                                 T("Session"): quality_txt(Sx["ctx"].session["quality"])})
                else:
                    a = Sx["analyses"]
                    rows.append({T("Symbol"): s, T("Grade"): "-", T("Side"): "-", T("Setup"): T("no clean setup"),
                                 T("Entry"): None, "R (TP2)": None,
                                 T("Session"): quality_txt(Sx["ctx"].session["quality"]) if Sx["ctx"] else ""})
            except Exception as ex:  # noqa: BLE001
                rows.append({T("Symbol"): s, T("Grade"): "-", T("Setup"): f"error: {ex}"[:60]})
        order = {"A+": 0, "A": 1, "B": 2, "C": 3}
        st.dataframe(pd.DataFrame(rows).sort_values(T("Grade"), key=lambda c: c.map(order).fillna(9)),
                     hide_index=True, use_container_width=True)

with t_j:
    st.caption(T("Every LONG/SHORT signal is logged. Evaluation: market entry, 1/3 off at each TP, stop to break-even after TP1."))
    jdf = journal.load()
    if jdf.empty:
        st.caption(T("No signals logged yet."))
    else:
        if st.button(T("Evaluate open signals")):
            for idx, row in jdf.iterrows():
                if str(row["outcome"]).startswith(("SL", "TP3")) or "BE" in str(row["outcome"]):
                    continue
                try:
                    candles, _ = get_candles(row["symbol"], "M5", source)
                    jdf.loc[idx, ["outcome", "r_multiple"]] = journal.evaluate(row, candles)
                except Exception as ex:  # noqa: BLE001
                    st.caption(f"{row['symbol']}: {ex}")
            journal.save(jdf)
        closed = jdf.dropna(subset=["r_multiple"]).sort_values("time")
        if not closed.empty:
            st.markdown(perf_card(T("Journal performance"), pd.to_numeric(closed["r_multiple"], errors="coerce").dropna()),
                        unsafe_allow_html=True)
        st.dataframe(jdf.sort_values("time", ascending=False), hide_index=True, use_container_width=True)

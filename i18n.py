"""UI translations: English (source), Mongolian (Cyrillic) and Simplified Chinese.

T("English text", **fmt) returns the text in the current language; missing entries fall back to English.
tr_dyn() translates engine / risk messages that are built with numbers inside.
"""
import re

LANGS = {"English": "en", "Монгол": "mn", "中文": "zh"}
AI_LANGUAGE = {"en": "English", "mn": "Mongolian (Cyrillic script)", "zh": "Simplified Chinese"}

_lang = "en"


def set_lang(code: str) -> None:
    global _lang
    _lang = code if code in ("en", "mn", "zh") else "en"


def lang() -> str:
    return _lang


# English -> (Mongolian, Chinese)
S = {
    # sidebar
    "Language": ("Хэл", "语言"),
    "Instrument": ("Хэрэгсэл", "交易品种"),
    "Timeframe": ("Хугацааны хүрээ", "时间周期"),
    "M15 = recommended scalping (backtested best) · M5 = fast scalping · H1+ = swing":
        ("M15 = санал болгох скальпинг (backtest-ээр хамгийн сайн) · M5 = хурдан скальпинг · H1+ = свинг",
         "M15 = 推荐剥头皮周期（回测最佳）· M5 = 快速剥头皮 · H1+ = 波段"),
    "Analyze": ("Шинжлэх", "分析"),
    "Live chart refresh (30 s)": ("Шууд шинэчлэл (30 сек)", "实时刷新（30 秒）"),
    "Updates price, chart and setups. Does not call the AI again.":
        ("Ханш, график, сетапыг шинэчилнэ. AI-г дахин дуудахгүй.", "更新价格、图表和形态，不会再次调用 AI。"),
    "Alert sound (setups & price alerts)": ("Дуут сануулга (сетап, ханш)", "提示音（形态与价格提醒）"),
    "Price alerts": ("Ханшийн сануулга", "价格提醒"),
    "e.g. 4100, 4075.5": ("жишээ нь 4100, 4075.5", "例如 4100, 4075.5"),
    "Comma-separated prices. With live refresh on you get a toast + beep when price crosses one.":
        ("Таслалаар тусгаарласан ханш. Шууд шинэчлэл асаалттай үед ханш түвшинг давахад мэдэгдэл, дуу гарна.",
         "用逗号分隔价格。开启实时刷新后，价格穿越时会弹出提示并响铃。"),
    "AI brain": ("AI тархи", "AI 大脑"),
    "Use AI (DeepSeek)": ("AI ашиглах (DeepSeek)", "使用 AI（DeepSeek）"),
    "Model": ("Загвар", "模型"),
    "chat = fast (~40 s, recommended) · reasoner = deeper but slow (~100 s)":
        ("chat = хурдан (~40 сек, санал болгох) · reasoner = гүнзгий боловч удаан (~100 сек)",
         "chat = 快速（约 40 秒，推荐）· reasoner = 更深入但较慢（约 100 秒）"),
    "No DeepSeek key in `.env` - run set_key.py. Rule engine is used meanwhile.":
        ("`.env`-д DeepSeek түлхүүр алга — set_key.py ажиллуулна уу. Одоогоор дүрмийн хөдөлгүүр ажиллана.",
         "`.env` 中没有 DeepSeek 密钥，请运行 set_key.py。暂时使用规则引擎。"),
    "Account & risk": ("Данс ба эрсдэл", "账户与风险"),
    "Balance (USD)": ("Үлдэгдэл (USD)", "余额（美元）"),
    "Minimum 20 USD. Small accounts are limited by the 0.01 minimum lot.":
        ("Хамгийн бага 20 USD. Жижиг данс 0.01 лотын доод хязгаартай.", "最低 20 美元。小账户受 0.01 最小手数限制。"),
    "Risk per trade %": ("Нэг арилжааны эрсдэл %", "每笔风险 %"),
    "Leverage 1:": ("Хөшүүрэг 1:", "杠杆 1:"),
    "**Risk guard** (prop-firm style)": ("**Эрсдэлийн хамгаалалт** (prop-firm дүрэм)", "**风控守卫**（自营公司规则）"),
    "Daily loss limit %": ("Өдрийн алдагдлын хязгаар %", "每日亏损上限 %"),
    "Max trades per day": ("Өдөрт хийх дээд арилжаа", "每日最多交易次数"),
    "Data": ("Өгөгдөл", "数据"),
    "Source": ("Эх сурвалж", "数据源"),
    "Testing / education only. Not financial advice.":
        ("Зөвхөн туршилт, сургалтад. Санхүүгийн зөвлөгөө биш.", "仅供测试与学习，不构成投资建议。"),

    # actions / status
    "Reading the tape… DeepSeek usually needs 30-90 s": ("Зах зээлийг уншиж байна… DeepSeek ихэвчлэн 30-90 сек", "正在读盘… DeepSeek 通常需要 30-90 秒"),
    "Could not analyze: {e}": ("Шинжилж чадсангүй: {e}", "分析失败：{e}"),
    "Could not load market data: {e}": ("Зах зээлийн өгөгдөл ачаалж чадсангүй: {e}", "无法加载行情数据：{e}"),
    "TradingView feed unavailable - showing {src}. Prices can differ from Pepperstone; re-run Analyze when the feed is back.":
        ("TradingView өгөгдөл тасарсан — {src} харуулж байна. Ханш Pepperstone-оос зөрж болно; өгөгдөл сэргэхэд дахин шинжилнэ үү.",
         "TradingView 行情不可用，当前显示 {src}。价格可能与 Pepperstone 不同，行情恢复后请重新分析。"),
    "High-impact news soon: ": ("Удахгүй өндөр нөлөөтэй мэдээ: ", "即将公布重要新闻："),
    "Risk guard: {why}. Signals are switched to WAIT for the rest of the day.":
        ("Эрсдэлийн хамгаалалт: {why}. Өнөөдрийн үлдсэн хугацаанд дохио ХҮЛЭЭХ горимд байна.",
         "风控守卫：{why}。今日剩余时间信号切换为观望。"),
    "daily loss limit hit ({p}% today, limit -{l}%)": ("өдрийн алдагдлын хязгаарт хүрсэн (өнөөдөр {p}%, хязгаар -{l}%)",
                                                      "已触及每日亏损上限（今日 {p}%，上限 -{l}%）"),
    "max {n} trades per day reached": ("өдрийн дээд {n} арилжаанд хүрсэн", "已达每日最多 {n} 笔交易"),
    "Risk guard: {why} - no new trades today.": ("Эрсдэлийн хамгаалалт: {why} — өнөөдөр шинэ арилжаа хийхгүй.", "风控守卫：{why}——今日不再开新仓。"),
    "Grade capped to {g}: {why}.": ("Зэргийг {g} хүртэл хязгаарласан: {why}.", "等级被限制为 {g}：{why}。"),
    "AI unavailable ({e}) - rule engine shown.": ("AI ажиллахгүй байна ({e}) — дүрмийн хөдөлгүүрийн дохио.", "AI 不可用（{e}），显示规则引擎结果。"),
    "Reset view": ("Харагдацыг сэргээх", "重置视图"),
    "Drag to pan · mouse wheel to zoom · double-click chart to reset":
        ("Чирж шилжүүлэх · хулганы дугуйгаар томруулах · давхар дарж сэргээх", "拖动平移 · 滚轮缩放 · 双击图表重置"),
    "Macro 24h": ("Макро 24ц", "宏观 24 小时"),
    "Setup radar": ("Сетап радар", "形态雷达"),
    "Nothing clean right now. No sweep, no VWAP retest, no fresh break. Waiting is a position.":
        ("Одоогоор цэвэр боломж алга: sweep, VWAP retest, шинэ эвдрэл байхгүй. Хүлээх нь ч позиц юм.",
         "目前没有清晰机会：无扫荡、无 VWAP 回踩、无新突破。观望也是一种仓位。"),
    "{sym} crossed {a} (now {p})": ("{sym} {a}-г давлаа (одоо {p})", "{sym} 穿越 {a}（现价 {p}）"),
    "New {g} {side} · {name} @ {e}": ("Шинэ {g} {side} · {name} @ {e}", "新信号 {g} {side} · {name} @ {e}"),

    # header
    "SCALPING TERMINAL": ("СКАЛЬПИНГ ТЕРМИНАЛ", "剥头皮终端"),
    "Change": ("Өөрчлөлт", "涨跌"),
    "Session": ("Сесс", "时段"),
    "LIVE FEED": ("ШУУД ӨГӨГДӨЛ", "实时行情"),
    "FALLBACK FEED": ("НӨӨЦ ӨГӨГДӨЛ", "备用行情"),
    "Next news": ("Дараагийн мэдээ", "下一条新闻"),
    "Today": ("Өнөөдөр", "今日"),
    "pips": ("пипс", "点"),
    "London open killzone": ("Лондонгийн нээлт (killzone)", "伦敦开盘黄金时段"),
    "New York open killzone": ("Нью-Йоркийн нээлт (killzone)", "纽约开盘黄金时段"),
    "London close": ("Лондонгийн хаалт", "伦敦收盘"),
    "Asia": ("Ази", "亚洲"),
    "London": ("Лондон", "伦敦"),
    "New York": ("Нью-Йорк", "纽约"),
    "between sessions": ("сесс хооронд", "时段间隙"),

    # verdict
    "Decision": ("Шийдвэр", "决策"),
    "STANDBY": ("БЭЛЭН", "待命"),
    "Engine sees:": ("Хөдөлгүүр харж байна:", "引擎发现："),
    "No clean setup on the radar.": ("Радар дээр цэвэр сетап алга.", "雷达上暂无清晰形态。"),
    "Press <b>ANALYZE</b> for the full AI read.": ("Бүрэн AI шинжилгээ авахын тулд <b>ШИНЖЛЭХ</b> дарна уу.", "点击<b>分析</b>获取完整 AI 解读。"),
    "WAIT": ("ХҮЛЭЭХ", "观望"),
    "BUY": ("АВАХ", "买入"),
    "SELL": ("ЗАРАХ", "卖出"),
    "BUY LIMIT": ("АВАХ ЛИМИТ", "限价买入"),
    "SELL LIMIT": ("ЗАРАХ ЛИМИТ", "限价卖出"),
    "BUY STOP": ("АВАХ СТОП", "突破买入"),
    "SELL STOP": ("ЗАРАХ СТОП", "突破卖出"),
    "MARKET": ("ЗАХ ЗЭЭЛИЙН ҮНЭ", "市价"),
    "LONG": ("АВАХ", "做多"),
    "SHORT": ("ЗАРАХ", "做空"),
    "Entry": ("Орох цэг", "入场"),
    "Stop": ("Стоп", "止损"),
    "Target {i}": ("Зорилт {i}", "目标 {i}"),
    "{lots} lot · risk {p}% (${r}) · margin ${m} @1:{lev}":
        ("{lots} лот · эрсдэл {p}% (${r}) · барьцаа ${m} @1:{lev}", "{lots} 手 · 风险 {p}%（${r}）· 保证金 ${m} @1:{lev}"),
    "Levels unavailable": ("Түвшин алга", "无价位"),
    "EXPIRED": ("ХУГАЦАА ДУУССАН", "已过期"),
    "VALID UNTIL": ("ХҮЧИНТЭЙ", "有效至"),
    "signal": ("дохио", "信号"),
    "Trigger": ("Орох нөхцөл", "触发条件"),
    "Plan": ("Төлөвлөгөө", "计划"),
    "Backtest edge": ("Backtest давуу тал", "回测优势"),
    "GRADE": ("ЗЭРЭГ", "等级"),
    "{w}% win · {r}R · {n} trades": ("{w}% ялалт · {r}R · {n} арилжаа", "胜率 {w}% · {r}R · {n} 笔"),

    # checklist
    "Pre-trade checklist · {ok}/{n} green": ("Арилжааны өмнөх шалгалт · {ok}/{n} ногоон", "交易前检查 · {ok}/{n} 通过"),
    "No setup to check": ("Шалгах сетап алга", "暂无可检查的形态"),
    "Higher-timeframe trend agrees": ("Том хугацааны чиг хандлага тохирч байна", "大周期趋势一致"),
    "Good session timing": ("Сессийн цаг тохиромжтой", "交易时段合适"),
    "Setup has a backtest edge": ("Сетап backtest-ээр ашигтай", "形态有回测优势"),
    "untested": ("туршаагүй", "未测试"),
    "No big news soon": ("Ойрд том мэдээ алга", "近期无重大新闻"),
    "clear": ("чөлөөтэй", "无"),
    "{n} min": ("{n} мин", "{n} 分钟"),
    "{name} confirms": ("{name} баталж байна", "{name} 确认"),
    "Room left in today's range": ("Өнөөдрийн хэлбэлзэлд зай байна", "今日波幅尚有空间"),
    "{u}% used": ("{u}% ашигласан", "已用 {u}%"),
    "Spread cost small": ("Спредийн зардал бага", "点差成本低"),
    "Account risk acceptable": ("Дансны эрсдэл зөвшөөрөгдөхүйц", "账户风险可接受"),
    "Daily risk guard": ("Өдрийн эрсдэлийн хамгаалалт", "每日风控"),
    "prime": ("оргил", "黄金时段"),
    "active": ("идэвхтэй", "活跃"),
    "slow": ("удаан", "清淡"),
    "market closed": ("зах хаалттай", "休市"),

    # gauges
    "Trend bias": ("Чиг хандлага", "趋势偏向"),
    "Strong bullish": ("Хүчтэй өсөх", "强势看涨"),
    "Bullish": ("Өсөх хандлагатай", "看涨"),
    "Strong bearish": ("Хүчтэй унах", "强势看跌"),
    "Bearish": ("Унах хандлагатай", "看跌"),
    "No clear trend": ("Тодорхой чиг алга", "无明确趋势"),
    "Price vs VWAP": ("Ханш ба VWAP", "价格 vs VWAP"),
    "Far above fair value": ("Шударга үнээс хол дээр", "远高于公允价值"),
    "Above fair value": ("Шударга үнээс дээр", "高于公允价值"),
    "Far below fair value": ("Шударга үнээс хол доор", "远低于公允价值"),
    "Below fair value": ("Шударга үнээс доор", "低于公允价值"),
    "At fair value": ("Шударга үнэ дээр", "处于公允价值"),
    "Day range used": ("Өдрийн хэлбэлзэл", "日内波幅使用"),
    "Exhausted - late to chase": ("Шавхагдсан — хөөхөд оройтсон", "已耗尽——追单太晚"),
    "Getting stretched": ("Сунаж байна", "趋于拉伸"),
    "Plenty of room": ("Зай их байна", "空间充足"),
    "Market mood": ("Зах зээлийн сэтгэл зүй", "市场情绪"),
    "RISK-ON": ("ЭРСДЭЛ ХҮСЭХ", "偏好风险"),
    "RISK-OFF": ("АЮУЛГҮЙ ХАЙХ", "避险"),
    "MIXED": ("ХОЛИМОГ", "混合"),
    "Investors buying risk": ("Хөрөнгө оруулагчид эрсдэлтэй хөрөнгө авч байна", "投资者在买入风险资产"),
    "Investors seeking safety": ("Хөрөнгө оруулагчид аюулгүй хөрөнгө хайж байна", "投资者在寻求避险"),
    "Mixed signals": ("Холимог дохио", "信号混杂"),

    # radar / tables
    "Grade": ("Зэрэг", "等级"), "Side": ("Чиглэл", "方向"), "Setup": ("Сетап", "形态"), "Backtest": ("Backtest", "回测"),
    "Order": ("Захиалга", "订单"), "Symbol": ("Хэрэгсэл", "品种"),
    "trades": ("арилжаа", "交易数"), "win %": ("ялалт %", "胜率 %"), "avg R": ("дундаж R", "平均 R"),
    "total R": ("нийт R", "总 R"), "profit factor": ("ашгийн харьцаа", "盈亏比"), "fill %": ("биелэлт %", "成交率 %"),

    # tabs
    "Analysis": ("Шинжилгээ", "分析"), "Market structure": ("Зах зээлийн бүтэц", "市场结构"),
    "News & calendar": ("Мэдээ ба календарь", "新闻与日历"), "Scanner": ("Сканнер", "扫描"), "Journal": ("Журнал", "交易日志"),
    "Run Analyze to see the reasoning.": ("Дүгнэлтийг харахын тулд Шинжлэх-ийг дарна уу.", "点击分析以查看推理过程。"),
    "Technical read": ("Техник шинжилгээ", "技术面"),
    "News & macro": ("Мэдээ ба макро", "新闻与宏观"),
    "Scenarios (next 1-2 h)": ("Хувилбарууд (дараагийн 1-2 цаг)", "情景（未来 1-2 小时）"),
    "Risks": ("Эрсдэлүүд", "风险"),
    "Model reasoning": ("Загварын бодол", "模型推理"),
    "score": ("оноо", "评分"),
    "Indicator": ("Үзүүлэлт", "指标"), "Reading": ("Утга", "读数"),
    "Structure log (execution timeframe)": ("Бүтцийн бүртгэл (гүйцэтгэлийн хугацаа)", "结构日志（执行周期）"),
    "Key levels": ("Гол түвшнүүд", "关键价位"),
    "Daily pivots": ("Өдрийн пивот", "日枢轴点"),
    "Unavailable: {e}": ("Боломжгүй: {e}", "不可用：{e}"),
    "No relevant headlines fetched.": ("Холбогдох мэдээ олдсонгүй.", "未获取到相关新闻。"),
    "Calendar unavailable.": ("Календарь боломжгүй.", "日历不可用。"),
    "Ccy": ("Валют", "货币"), "Impact": ("Нөлөө", "影响"), "Event": ("Үйл явдал", "事件"),
    "Fcst": ("Таамаг", "预测"), "Prev": ("Өмнөх", "前值"), "Actual": ("Бодит", "实际"),
    "Backtest covers the scalping setups (M5 / M15).": ("Backtest нь скальпинг сетапуудыг (M5 / M15) хамарна.", "回测仅覆盖剥头皮形态（M5 / M15）。"),
    "Run backtest": ("Backtest ажиллуулах", "运行回测"),
    "Replays ~5,000 bars bar-by-bar. Takes 1-3 minutes.": ("~5,000 лааг нэг бүрчлэн дахин тоглуулна. 1-3 минут.", "逐根回放约 5000 根 K 线，需 1-3 分钟。"),
    "Engine settings changed since the last run - these stats no longer apply. Run the backtest again.":
        ("Сүүлийн ажиллуулснаас хойш хөдөлгүүрийн тохиргоо өөрчлөгдсөн — эдгээр үзүүлэлт хүчингүй. Backtest-ийг дахин ажиллуулна уу.",
         "引擎设置自上次运行后已更改，这些统计不再适用，请重新运行回测。"),
    "{sym} {tf} · {bars} bars · {a} → {b} UTC · updated {h} h ago. Walk-forward, no look-ahead, spread included; half off at TP1, stop to break-even, rest to TP2, flat after 3 h.":
        ("{sym} {tf} · {bars} лаа · {a} → {b} UTC · {h} цагийн өмнө шинэчилсэн. Walk-forward, ирээдүйг харахгүй, спред тооцсон; TP1-д хагасыг хааж, стопыг break-even, үлдсэнийг TP2, 3 цагийн дараа хаана.",
         "{sym} {tf} · {bars} 根K线 · {a} → {b} UTC · {h} 小时前更新。滚动回测、无未来函数、含点差；TP1 平半仓并保本，其余至 TP2，3 小时后平仓。"),
    "No backtest yet for this market. Run it once; results are saved and reused.":
        ("Энэ зах зээлд backtest хийгээгүй байна. Нэг удаа ажиллуулахад үр дүн хадгалагдана.", "该品种尚无回测。运行一次后结果会被保存复用。"),
    "Replaying history…": ("Түүхийг дахин тоглуулж байна…", "正在回放历史…"),
    "Backtest failed: {e}": ("Backtest амжилтгүй: {e}", "回测失败：{e}"),
    "Trades": ("Арилжаа", "交易数"), "Win rate": ("Ялалтын хувь", "胜率"), "Avg R / trade": ("Дундаж R / арилжаа", "平均 R / 笔"),
    "Total R": ("Нийт R", "总 R"), "cumulative R": ("хуримтлагдсан R", "累计 R"),
    "By setup": ("Сетапаар", "按形态"), "By grade": ("Зэргээр", "按等级"), "By session": ("Сессээр", "按时段"), "By side": ("Чиглэлээр", "按方向"),
    "By hour of day (UTC) - weak hours lower the grade live": ("Цаг тутмаар (UTC) — сул цагууд шууд зэргийг бууруулна", "按小时（UTC）——弱势时段会实时降低等级"),
    "Past results over ~{d} days. Small samples are noisy; treat this as evidence, not a promise.":
        ("Сүүлийн ~{d} өдрийн үр дүн. Жижиг түүвэр санамсаргүй байж болно; амлалт биш, нотолгоо гэж үзнэ үү.",
         "过去约 {d} 天的结果。样本小噪音大，请视为证据而非承诺。"),
    "Best rule-engine setup on {tf} for every instrument. No AI cost.": ("Бүх хэрэгслийн {tf} дээрх хамгийн сайн сетап. AI зардалгүй.", "各品种在 {tf} 上的最佳规则引擎形态，不消耗 AI。"),
    "Scan all instruments": ("Бүх хэрэгслийг шалгах", "扫描全部品种"),
    "no clean setup": ("цэвэр сетап алга", "无清晰形态"),
    "Every LONG/SHORT signal is logged. Evaluation: market entry, 1/3 off at each TP, stop to break-even after TP1.":
        ("АВАХ/ЗАРАХ дохио бүр бүртгэгдэнэ. Үнэлгээ: зах зээлийн үнээр орж, TP бүрт 1/3-ийг хааж, TP1-ийн дараа стопыг break-even.",
         "每个做多/做空信号都会记录。评估：市价入场，每个 TP 平 1/3，TP1 后止损移至保本。"),
    "No signals logged yet.": ("Дохио бүртгэгдээгүй байна.", "尚无信号记录。"),
    "Evaluate open signals": ("Нээлттэй дохиог үнэлэх", "评估未平仓信号"),
    "Closed": ("Хаагдсан", "已平仓"),
}

S.update({
    "Order block": ("Order block", "订单块"),
    "Signals in view: {n} · won {w} · lost {l} · open {o}": ("Дэлгэц дээрх дохио: {n} · ✓{w} · ✗{l} · ⏳{o}",
                                                             "可见信号：{n} · 盈 {w} · 亏 {l} · 持仓 {o}"),
    "Backtest performance": ("Backtest үр дүн", "回测表现"),
    "Analyzing…": ("Шинжилж байна…", "分析中…"),
    "Show no-edge signals (B grade) on chart": ("Давуу талгүй (B) дохиог график дээр харуулах", "在图表显示无优势信号（B 级）"),
    "Signals in view: {n} · won {w} · lost {l} · open {o}": ("Дэлгэц дээрх дохио: {n} · ✓{w} · ✗{l} · ⏳{o}",
                                                             "可见信号：{n} · 盈 {w} · 亏 {l} · 持仓 {o}"),
    "No tradeable (A/A+) signals in view - no-edge B/C signals are hidden":
        ("Дэлгэц дээр арилжаалах (A/A+) дохио алга — давуу талгүй B/C дохиог нуусан", "可见范围内无可交易（A/A+）信号——无优势的 B/C 信号已隐藏"),
    "Similar past setups": ("Ижил төстэй өнгөрсөн сетапууд", "相似历史形态"),
    "won {w}% · {r}R (unseen data)": ("{w}% ялсан · {r}R (шинэ өгөгдөл)", "胜率 {w}% · {r}R（样本外）"),
    "M5 failed the unseen-data test (it looked good on past data, then lost). Use it to watch price; take trades from M15.":
        ("M5 шинэ өгөгдөл дээрх шалгалтад унасан (өнгөрсөнд сайн харагдаад, дараа нь алдагдал хүлээсэн). Ханшийг ажиглахад ашиглаж, арилжааг M15-аас авна уу.",
         "M5 未通过样本外测试（历史数据看似不错，之后亏损）。用它看盘，交易请以 M15 为准。"),
    "What the app has learned on {sym} {tf}": ("Апп {sym} {tf} дээр юу сурсан бэ", "应用在 {sym} {tf} 上学到的经验"),
    "These measured lessons are sent to DeepSeek with every analysis.":
        ("Эдгээр хэмжигдсэн сургамжийг шинжилгээ бүрт DeepSeek-д илгээдэг.", "这些经实测得出的经验会随每次分析发送给 DeepSeek。"),
    "Loading market data and running the engine": ("Зах зээлийн өгөгдөл ачаалж, хөдөлгүүрийг ажиллуулж байна", "加载行情并运行引擎"),
    "DeepSeek is reading the market ({m})…": ("DeepSeek зах зээлийг уншиж байна ({m})…", "DeepSeek 正在读盘（{m}）…"),
    "Done in {s} s": ("{s} секундэд дууслаа", "{s} 秒完成"),
    "This analysis was written in {l}. Press Analyze to refresh it in the current language.":
        ("Энэ шинжилгээ {l} хэл дээр хийгдсэн. Одоогийн хэлээр харахын тулд Шинжлэх дарна уу.",
         "此分析使用 {l} 生成。点击分析以当前语言刷新。"),
    "Journal performance": ("Журналын үр дүн", "交易日志表现"),
})

S.update({
    "Strategy": ("Стратеги", "策略"),
    "Auto - best tested for this market": ("Авто — энэ зах зээлд хамгийн сайн туршигдсан", "自动——该品种回测最佳"),
    "Pro Pullback + trailing stop": ("Pro Pullback + дагах стоп", "Pro Pullback + 移动止损"),
    "Signal v26 + trailing stop": ("Signal v26 + дагах стоп", "世界最强信号 v26 + 移动止损"),
    "Smart-money engine (experimental)": ("Smart-money хөдөлгүүр (туршилтын)", "聪明钱引擎（实验）"),
    "Show market structure (HH/HL/LH/LL, BOS/CHoCH)": ("Зах зээлийн бүтэц харуулах (HH/HL/LH/LL, BOS/CHoCH)", "显示市场结构（HH/HL/LH/LL、BOS/CHoCH）"),
    "Show weak / no-edge engine signals on chart": ("Сул / давуу талгүй дохиог графикт харуулах", "在图表显示弱/无优势引擎信号"),
    "Rule-based plan": ("Дүрэмд суурилсан төлөвлөгөө", "规则交易计划"),
    "Neither of your strategies made money on {sym} in testing - no trades here.":
        ("Таны хоёр стратеги {sym} дээр туршилтад ашиг өгөөгүй — энд арилжаа хийхгүй.", "你的两个策略在 {sym} 回测中均未盈利——此品种不交易。"),
    "In a {side} trade since {t} UTC. The stop now trails at {s}.":
        ("{t} UTC-ээс хойш {side} арилжаанд байна. Стоп одоо {s} дээр дагаж байна.", "自 {t} UTC 起持有{side}仓位，止损现跟随至 {s}。"),
    "Waiting for a Signal v26 setup (trend + RSI + engulfing/pin bar + volume).":
        ("Signal v26 сетап хүлээж байна (чиг + RSI + engulfing/pin bar + эзлэхүүн).", "等待 v26 信号（趋势 + RSI + 吞没/针形 + 成交量）。"),
    "4H trend is unclear (EMA50/EMA200 not aligned) - no trades until it is.":
        ("4H чиг тодорхойгүй (EMA50/EMA200 зэрэгцээгүй) — тодрох хүртэл арилжаа хийхгүй.", "4H 趋势不明（EMA50/EMA200 未排列）——明确前不交易。"),
    "active session": ("идэвхтэй сесс", "活跃时段"), "ADX ≥ 20": ("ADX ≥ 20", "ADX ≥ 20"), "structure": ("бүтэц", "结构"),
    "pullback to EMA20": ("EMA20 руу буцалт", "回踩 EMA20"), "confirmation candle": ("баталгаажуулах лаа", "确认K线"),
    "4H trend says {side} only. Waiting for: {m}.": ("4H чиг зөвхөн {side}. Хүлээж буй нөхцөл: {m}.", "4H 趋势只做{side}。等待：{m}。"),
    "stop within 3×ATR": ("стоп 3×ATR дотор", "止损在 3×ATR 内"),
    "IN TRADE": ("АРИЛЖААНД", "持仓中"),
    "New signal on the last closed candle.": ("Сүүлд хаагдсан лаан дээр шинэ дохио.", "最新收盘K线出现新信号。"),
    "Open since {t} UTC · now {r}R": ("{t} UTC-ээс нээлттэй · одоо {r}R", "自 {t} UTC 持仓 · 当前 {r}R"),
    "Initial stop": ("Анхны стоп", "初始止损"), "Trailing stop now": ("Одоогийн дагах стоп", "当前移动止损"),
    "locked": ("баталгаажсан", "已锁定"),
    "EURUSD deep dip-buy + news-spike filter (10y tested)": ("EURUSD гүн уналтын худалдан авалт + мэдээний шүүлтүүр (10 жил шалгасан)",
                                                             "EURUSD 深跌买入 + 新闻尖峰过滤（10 年回测）"),
    "RSI(2) below 2 with no news spike": ("RSI(2) 2-оос доош, мэдээний огцом хөдөлгөөнгүй", "RSI(2) 低于 2 且无新闻尖峰"),
    "No news spike in the last 3 candles": ("Сүүлийн 3 лаанд мэдээний огцом хөдөлгөөн алга", "最近 3 根K线无新闻尖峰"),
    "PF older {a} / newer {b}": ("PF хуучин {a} / шинэ {b}", "PF 早期 {a} / 近期 {b}"),
    "High-impact news at {t} UTC ({e}) - wait until it is out and the candle closes calm.":
        ("{t} UTC-д чухал мэдээ ({e}) - мэдээ гарч, лаа тайван хаагдтал хүлээ.", "{t} UTC 有重要新闻（{e}）- 等新闻公布、K线平稳收盘后再说。"),
    "Stop 3×ATR below entry. Target: close the trade when a candle closes back above the 5-period average (the bounce) - usually within a few hours. Skipped when a news spike candle printed in the last 3 hours. Signals come from the H1 chart and show on any chart.":
        ("Стоп орлтоос 3×ATR доор. Зорилт: лаа 5-ын дунджаас дээш хаагдахад (сэргэлт) арилжааг хаа - ихэвчлэн хэдхэн цагт. Сүүлийн 3 цагт мэдээний огцом лаа гарсан бол алгасна. Дохио H1 графикаас ирж, бүх график дээр харагдана.",
         "止损在入场价下方 3×ATR。目标：K线收回 5 周期均线上方（反弹）时平仓，通常几小时内。最近 3 小时出现新闻尖峰K线则跳过。信号来自 H1 图表，在任何周期图上都会显示。"),
    "EURUSD dip-buy / rally-sell + news-spike filter (10y tested)": ("EURUSD уналтад авах / өсөлтөд зарах + мэдээний шүүлтүүр (10 жил шалгасан)",
                                                                     "EURUSD 逢低买入 / 逢高卖出 + 新闻尖峰过滤（10 年回测）"),
    "deep dip": ("гүн уналт", "深度回调"), "2-candle dip": ("2 лааны уналт", "两根K线回调"), "rally sell": ("өсөлтөд зарах", "反弹卖出"),
    "buy dips": ("уналтад авах", "逢低买入"), "sell rallies": ("өсөлтөд зарах", "逢高卖出"), "Signal": ("Дохио", "信号"),
    "Trend (200-period average)": ("Чиг хандлага (200-ын дундаж)", "趋势（200 周期均线）"),
    "Exit when price closes back across": ("Үнэ буцаж огтлон хаагдахад гар", "价格收回穿越时离场"),
    "A news-spike candle printed in the last 3 hours - signals paused until the market calms down.":
        ("Сүүлийн 3 цагт мэдээний огцом лаа гарсан - зах зээл тайвшртал дохио түр зогсоно.", "最近 3 小时出现新闻尖峰K线 - 信号暂停，直到市场平静。"),
    "Uptrend (above the 200-average): waiting to BUY a dip - RSI(2) under 2, or the last 2 candles' RSI(2) adding up to under 10. Now {v}.":
        ("Өсөх хандлага (200-ын дунджаас дээш): уналтад АВАХЫГ хүлээж байна - RSI(2) 2-оос доош, эсвэл сүүлийн 2 лааны RSI(2)-ийн нийлбэр 10-аас доош. Одоо {v}.",
         "上升趋势（200 均线上方）：等待逢低买入 - RSI(2) 低于 2，或最近 2 根K线 RSI(2) 之和低于 10。当前 {v}。"),
    "Downtrend (below the 200-average): waiting to SELL a sharp rally - RSI(2) above 98. Now RSI(2) {v}.":
        ("Буурах хандлага (200-ын дунджаас доош): огцом өсөлтөд ЗАРАХЫГ хүлээж байна - RSI(2) 98-аас дээш. Одоо RSI(2) {v}.",
         "下降趋势（200 均线下方）：等待逢高卖出 - RSI(2) 高于 98。当前 RSI(2) {v}。"),
    "Stop 3×ATR from entry. Target: close the trade when a candle closes back across the 5-period average (the snap-back) - usually within a few hours. Buys dips in an uptrend, sells rallies in a downtrend. Skipped after a news-spike candle and when the whole dollar is moving (checked against GBPUSD). Signals come from the H1 chart and show on any chart.":
        ("Стоп орлтоос 3×ATR. Зорилт: лаа 5-ын дунджийг буцаж огтлон хаагдахад арилжааг хаа - ихэвчлэн хэдхэн цагт. Өсөх үед уналтад авч, буурах үед өсөлтөд зарна. Мэдээний огцом лааны дараа болон ам.доллар бүхэлдээ хөдөлж байх үед (GBPUSD-ээр шалгана) алгасна. Дохио H1 графикаас ирж, бүх график дээр харагдана.",
         "止损距入场 3×ATR。目标：K线收回穿越 5 周期均线（回归）时平仓，通常几小时内。上升趋势逢低买入，下降趋势逢高卖出。新闻尖峰K线后以及整个美元波动时（用 GBPUSD 检查）跳过。信号来自 H1 图表，在任何周期图上都会显示。"),
    "Exit level now": ("Одоогийн гарах түвшин", "当前离场位"), "if hit": ("хүрвэл", "若触发"),
    "HIT": ("ХҮРСЭН", "已达成"), "{p}% reach": ("{p}% хүрдэг", "{p}% 到达"), "Exit (bounce)": ("Гарах (сэргэлт)", "离场（回归）"),
    "{p}% of past trades reached it": ("Өмнөх арилжааны {p}% хүрсэн", "{p}% 的历史交易到达过"),
    "TP1/TP2/TP3 show how far past signals ran: {a}% reached TP1, {b}% TP2, {c}% TP3. Safer option: close 1/3 at each TP and move the stop to breakeven after TP1 - won 80% of trades in testing, but about 40% less profit than holding to the bounce exit.":
        ("TP1/TP2/TP3 нь өмнөх дохио хэр хол явсныг харуулна: {a}% TP1, {b}% TP2, {c}% TP3-д хүрсэн. Илүү аюулгүй хувилбар: TP бүр дээр 1/3-ийг хааж, TP1-ийн дараа стопыг орлтын үнэ рүү шилжүүл - туршилтад 80% хожсон ч сэргэлт хүртэл барихаас ~40% бага ашигтай.",
         "TP1/TP2/TP3 显示历史信号走了多远：{a}% 到达 TP1，{b}% 到达 TP2，{c}% 到达 TP3。更稳妥的做法：每个 TP 平 1/3，TP1 后止损移至保本 - 回测胜率 80%，但利润比持有到回归离场少约 40%。"),
    "EUR-only move (GBPUSD not moving as much)": ("Зөвхөн EUR-ийн хөдөлгөөн (GBPUSD тийм их хөдлөөгүй)", "仅欧元波动（GBPUSD 未同幅波动）"),
    "no GBPUSD data": ("GBPUSD өгөгдөл алга", "无 GBPUSD 数据"),
    "The whole US dollar is moving (GBPUSD moved as much as EURUSD) - snap-backs had no edge in that case, so signals wait.":
        ("Ам.доллар бүхэлдээ хөдөлж байна (GBPUSD нь EURUSD-тэй адил хөдөлсөн) - ийм үед сэргэлт ашиггүй байсан тул дохио хүлээнэ.",
         "整个美元在波动（GBPUSD 与 EURUSD 同幅波动）- 这种情况下回归没有优势，信号等待。"),
    "Stop 3×ATR from entry. TP1 (+0.25×ATR, a few pips): close HALF and move the stop to breakeven - 85% of past trades reached it, which is why 83% of trades ended in profit. The other half: close when a candle closes back across the 5-period average (the snap-back). TP2/TP3 show how far moves usually ran ({b}% / {c}%). Buys dips in an uptrend, sells rallies in a downtrend; skipped after a news spike, on a structure break (new 30-candle low/high) and when the whole dollar is moving (checked against GBPUSD). You need at least 0.02 lot to close half.":
        ("Стоп орлтоос 3×ATR. TP1 (+0.25×ATR, хэдхэн пипс): ТАЛЫГ хааж стопыг орлтын үнэ рүү шилжүүл - өмнөх арилжааны 85% хүрсэн тул 83% нь ашигтай дууссан. Нөгөө тал: лаа 5-ын дунджийг буцаж огтлон хаагдахад хаа (сэргэлт). TP2/TP3 нь хөдөлгөөн хэр хол явдгийг харуулна ({b}% / {c}%). Өсөх үед уналтад авч, буурах үед өсөлтөд зарна; мэдээний огцом хөдөлгөөний дараа, бүтэц эвдрэх үед (30 лааны шинэ доод/дээд) болон ам.доллар бүхэлдээ хөдөлж байхад (GBPUSD-ээр шалгана) алгасна. Талыг хаахын тулд хамгийн багадаа 0.02 лот хэрэгтэй.",
         "止损距入场 3×ATR。TP1（+0.25×ATR，几个点）：平掉一半并把止损移至保本 - 85% 的历史交易到达过，所以 83% 的交易以盈利结束。另一半：K线收回穿越 5 周期均线（回归）时平仓。TP2/TP3 显示行情通常走多远（{b}% / {c}%）。上升趋势逢低买入，下降趋势逢高卖出；新闻尖峰后、结构突破时（30 根K线新低/新高）以及整个美元波动时（用 GBPUSD 检查）跳过。平一半至少需要 0.02 手。"),
    "Assumes ~0.9 pip total cost (Pepperstone Razor: raw spread + commission). On a Standard account (~1.2 pips) the same test wins 77%; at 1.5 pips 65%.":
        ("~0.9 пипс нийт зардал гэж тооцсон (Pepperstone Razor: түүхий спред + комисс). Standard данс (~1.2 пипс) дээр ижил тест 77% хожно; 1.5 пипс бол 65%.",
         "按约 0.9 点总成本计算（Pepperstone Razor：原始点差 + 佣金）。Standard 账户（约 1.2 点）同样测试胜率 77%；1.5 点时 65%。"),
    "No structure break (not a new 30-candle low/high)": ("Бүтэц эвдрээгүй (30 лааны шинэ доод/дээд биш)", "无结构突破（非 30 根K线新低/新高）"),
    "break - skip": ("эвдэрсэн - алгас", "已突破 - 跳过"), "clear": ("цэвэр", "正常"),
    "Price just broke the last 30 candles' range (LL/BOS) - that is a structure break, not a dip, so signals wait.":
        ("Үнэ сүүлийн 30 лааны мужийг эвдлээ (LL/BOS) - энэ нь уналт биш бүтцийн эвдрэл тул дохио хүлээнэ.",
         "价格刚跌破/突破最近 30 根K线区间（LL/BOS）- 这是结构突破而不是回调，信号等待。"),
    "📧 Gmail alerts ready. Start run_alerts.bat to get emails even with this page closed.":
        ("📧 Gmail мэдэгдэл бэлэн. Энэ хуудсыг хаасан ч имэйл авахын тулд run_alerts.bat-ийг ажиллуул.",
         "📧 Gmail 提醒已就绪。运行 run_alerts.bat，即使关闭此页面也能收到邮件。"),
    "📧 Send test email": ("📧 Туршилтын имэйл илгээх", "📧 发送测试邮件"),
    "📧 Gmail alerts: not set up yet - run set_email.py (needs a Gmail App Password).":
        ("📧 Gmail мэдэгдэл тохируулаагүй - set_email.py-г ажиллуул (Gmail App Password хэрэгтэй).",
         "📧 Gmail 提醒尚未设置 - 运行 set_email.py（需要 Gmail 应用专用密码）。"),
    "Test email sent - check your Gmail (and the Spam folder).": ("Туршилтын имэйл илгээлээ - Gmail-ээ (Spam хавтсыг ч) шалга.",
                                                                  "测试邮件已发送 - 请查看 Gmail（以及垃圾邮件）。"),
    "Email failed: {e}": ("Имэйл илгээж чадсангүй: {e}", "邮件发送失败：{e}"),
    "Gold deep dip-buy + daily trend + dollar check (10y tested)": ("Алтны гүн уналтад авах + өдрийн чиг + долларын шалгалт (10 жил шалгасан)",
                                                                    "黄金深跌买入 + 日线趋势 + 美元检查（10 年回测）"),
    "Gold buys dips only while the daily trend and the H1 trend are both up - that is not the case now, so it waits.":
        ("Алт зөвхөн өдрийн болон H1 чиг хоёулаа өсөх үед уналтад авна - одоо тийм биш тул хүлээнэ.", "黄金只在日线和 H1 趋势都向上时逢低买入 - 现在不是，所以等待。"),
    "The whole US dollar is moving (EURUSD moved as much as gold) - signals wait.": ("Ам.доллар бүхэлдээ хөдөлж байна (EURUSD алттай адил хөдөлсөн) - дохио хүлээнэ.",
                                                                                    "整个美元在波动（EURUSD 与黄金同幅波动）- 信号等待。"),
    "Uptrend on H1 and daily: waiting to BUY a deep dip (RSI(2) under 2). Now RSI(2) {v}.": ("H1 ба өдрийн чиг өсөж байна: гүн уналтад АВАХЫГ хүлээж байна (RSI(2) 2-оос доош). Одоо RSI(2) {v}.",
                                                                                            "H1 和日线上升：等待深跌买入（RSI(2) 低于 2）。当前 RSI(2) {v}。"),
    "H1 uptrend (above the 200-average)": ("H1 өсөх чиг (200-ын дунджаас дээш)", "H1 上升（200 均线上方）"),
    "Daily uptrend (above the 50-day average)": ("Өдрийн өсөх чиг (50 хоногийн дунджаас дээш)", "日线上升（50 日均线上方）"),
    "Deep dip (RSI(2) under 2)": ("Гүн уналт (RSI(2) 2-оос доош)", "深度回调（RSI(2) 低于 2）"),
    "Gold-only move (EURUSD not moving as much)": ("Зөвхөн алтны хөдөлгөөн (EURUSD тийм их хөдлөөгүй)", "仅黄金波动（EURUSD 未同幅波动）"),
    "no EURUSD data": ("EURUSD өгөгдөл алга", "无 EURUSD 数据"), "yes": ("тийм", "是"), "no": ("үгүй", "否"),
    'A · high accuracy': ('A · өндөр нарийвчлал', 'A · 高准确率'),
    'B · trend trade': ('B · чиг хандлагын арилжаа', 'B · 趋势交易'),
    'Signal board · every tested plan': ('Дохионы самбар · шалгасан бүх төлөвлөгөө', '信号面板 · 所有回测过的方案'),
    'Waiting for': ('Хүлээж буй', '等待'),
    'setup': ('бэлтгэл', '条件'),
    'Tested': ('Туршсан', '回测'),
    'win': ('хожил', '胜率'),
    'month': ('сар', '月'),
    'Now': ('Одоо', '现在'),
    'No data': ('Өгөгдөл алга', '无数据'),
    'No fixed TP - trailing stop 3×ATR behind the best price': ('Тогтмол TP байхгүй - стоп хамгийн сайн үнээс 3×ATR ард дагана', '无固定止盈 - 止损跟随最佳价格 3×ATR'),
    'A = high accuracy (83-91% win, small wins). B = trend trade (~40% win, trailing stop, bigger wins). The meter counts the conditions met now; a signal comes only at full.': ('A = өндөр нарийвчлал (83-91% хожил, бага ашиг). B = чиг хандлагын арилжаа (~40% хожил, дагах стоп, том ашиг). Хэмжүүр одоо биелсэн нөхцлийг тоолно; бүгд биелэхэд л дохио гарна.', 'A = 高准确率（胜率 83-91%，盈利小）。B = 趋势交易（胜率约 40%，移动止损，盈利大）。进度条显示当前满足的条件数，全部满足才出信号。'),
    'Gold deep dip': ('Алтны гүн уналт', '黄金深跌'),
    'EURUSD dip-buy / rally-sell': ('EURUSD уналтад авах / өсөлтөд зарах', 'EURUSD 逢低买入 / 逢高卖出'),
    'Gold trend: EMA20 pullback buy': ('Алтны чиг: EMA20 руу ухрахад авах', '黄金趋势：回踩 EMA20 买入'),
    'Gold trend: Pro Pullback': ('Алтны чиг: Pro Pullback', '黄金趋势：Pro Pullback'),
    'Chart indicators': ('Графикийн индикаторууд', '图表指标'),
    'Lower panel': ('Доод самбар', '下方面板'),
    'Bollinger Bands': ('Боллинжерийн зурвас', '布林带'),
    'Fibonacci': ('Фибоначчи', '斐波那契'),
    'Order blocks': ('Захиалгын блок (OB)', '订单块 (OB)'),
    'FVG & sweeps': ('FVG ба хөрвөх чадварын шүүрдэлт', 'FVG 与流动性扫荡'),
    'Key levels': ('Гол түвшнүүд', '关键价位'),
    'Market structure': ('Зах зээлийн бүтэц', '市场结构'),
    'Volume': ('Хэмжээ (volume)', '成交量'),
    'Time Machine': ('Цагийн машин', '时间机器'),
    'Time Machine · replay a trade 10,000 times': ('Цагийн машин · арилжааг 10,000 удаа давтан тоглуулах', '时间机器 · 把一笔交易重放 10,000 次'),
    "Each replay strings together random blocks of this market's real recent 15-minute candles, starting at your entry. It shows how wide the outcomes are - not which one will happen. The tested plan numbers are more reliable.": ('Давталт бүр энэ зах зээлийн сүүлийн бодит 15 минутын лаануудаас санамсаргүй хэсгүүдийг таны орлтоос эхлэн холбоно. Үр дүн хэр өргөн тархаж болохыг харуулна - алийг нь болохыг биш. Шалгасан төлөвлөгөөний тоо илүү найдвартай.', '每次重放都从你的入场价开始，把这个市场最近真实的 15 分钟K线随机拼接起来。它显示结果的分布有多宽，而不是哪个会发生。回测过的方案数据更可靠。'),
    'Market': ('Зах зээл', '市场'),
    'Direction': ('Чиглэл', '方向'),
    'Target': ('Зорилт', '目标'),
    'Hours to replay': ('Давтах цаг', '重放小时数'),
    'Run 10,000 replays': ('10,000 удаа давтах', '运行 10,000 次重放'),
    'Target first': ('Эхлээд зорилт', '先到目标'),
    'Stop first': ('Эхлээд стоп', '先到止损'),
    'Neither in time': ('Аль нь ч хүрээгүй', '期间都未触及'),
    'Average result': ('Дундаж үр дүн', '平均结果'),
    'Sample replays': ('Жишээ давталтууд', '重放示例'),
    'Where price ends': ('Үнэ хаана дуусах', '价格终点分布'),
    'Prefilled with the open {sym} trade from the signal board.': ('Дохионы самбарын нээлттэй {sym} арилжаагаар бөглөсөн.', '已用信号面板中 {sym} 的持仓预填。'),
    'R = your stop distance. Above 0 means this trade paid on average in the replays.': ('R = таны стопын зай. 0-ээс дээш бол давталтуудад дунджаар ашигтай.', 'R = 止损距离。大于 0 表示在重放中平均盈利。'),
    'For a buy the stop must be below the entry and the target above it (the other way round for a sell).': ('Авахад стоп орлтоос доор, зорилт дээр байх ёстой (зарахад эсрэгээр).', '买入时止损须低于入场价、目标高于入场价（卖出相反）。'),
    "Risk:reward 1:{rr}. A high 'target first' with a far stop can still lose money on average - check the average result.": ("Эрсдэл:ашиг 1:{rr}. Стоп хол байвал 'эхлээд зорилт' өндөр байсан ч дунджаар алдагдалтай байж болно - дундаж үр дүнг шалга.", "风险回报 1:{rr}。止损很远时，'先到目标'比例高也可能平均亏损 - 请看平均结果。"),
    'Stop': ('Стоп', '止损'),
    'Simple view': ('Энгийн харагдац', '简洁视图'),
    'Only the most profitable signal and its reasons. Turn off for the full terminal.': ('Зөвхөн хамгийн ашигтай дохио ба шалтгаан. Бүрэн терминал харахын тулд унтраа.', '只显示最赚钱的信号和原因。关闭可看完整终端。'),
    'Chart & full analysis': ('График ба бүрэн шинжилгээ', '图表与完整分析'),
    'More tools · Time Machine, news, backtest, journal': ('Бусад хэрэгсэл · Цагийн машин, мэдээ, туршилт, тэмдэглэл', '更多工具 · 时间机器、新闻、回测、日志'),
    'Most profitable signal': ('Хамгийн ашигтай дохио', '最赚钱的信号'),
    'Profit': ('Ашиг', '盈利'),
    'Why this signal': ('Яагаад энэ дохио', '为什么是这个信号'),
    'What this signal needs': ('Энэ дохионд юу хэрэгтэй', '这个信号还需要什么'),
    'no signal right now': ('одоогоор дохио алга', '目前没有信号'),
    'Closest': ('Хамгийн ойр', '最接近'),
    'signal since': ('дохио эхэлсэн', '信号开始于'),
    'now': ('одоо', '现在'),
    'close half': ('талыг хаа', '平一半'),
    'trailing stop - after each hourly candle, move your stop to the Stop loss shown here': ('дагах стоп - цагийн лаа бүрийн дараа стопоо энд харагдах Stop loss руу шилжүүл', '移动止损 - 每根小时 K 线收盘后，把止损移到这里显示的止损价'),
    'lot': ('лот', '手'),
    'risk': ('эрсдэл', '风险'),
    'All signals · most profitable first': ('Бүх дохио · хамгийн ашигтай нь эхэндээ', '所有信号 · 最赚钱的在前'),
    'No market data right now - try again in a minute.': ('Одоогоор өгөгдөл алга - нэг минутын дараа дахин оролдоно уу.', '暂时没有行情数据 - 请一分钟后再试。'),
    'Tested {y} years: about +{m}% of your account a month at 1% risk per trade · wins {w}% of trades · the average win is {x}× the average loss': ('{y} жил туршсан: арилжаа бүрт 1% эрсдэлээр сард дансны ойролцоогоор +{m}% · арилжааны {w}% хожсон · дундаж ашиг нь дундаж алдагдлаас {x} дахин их', '{y} 年回测：每笔风险 1% 时每月约 +{m}% · {w}% 的交易盈利 · 平均盈利是平均亏损的 {x} 倍'),
    'How this signal works': ('Энэ дохио хэрхэн ажилладаг', '这个信号如何运作'),
    'Opening range': ('Нээлтийн муж', '开盘区间'),
    'Opening-range breakout · watch the open': ('Нээлтийн мужийн эвдрэл · нээлтийг ажигла', '开盘区间突破 · 盯盘开盘'),
    'Session': ('Сешн', '时段'),
    'Range': ('Муж', '区间'),
    'Opening range high': ('Нээлтийн мужийн дээд', '开盘区间高点'),
    'Entry rule': ('Орох дүрэм', '入场规则'),
    'Entry timer': ('Орох цаг хэмжигч', '入场计时'),
    'Close above': ('Дээгүүр хаагдах', '收盘高于'),
    'Close below': ('Доогуур хаагдах', '收盘低于'),
    'the range high (buy) or low (sell), 5-min candle close': ('мужийн дээд (авах) эсвэл доод (зарах), 5 минутын лааны хаалт', '区间高点（买）或低点（卖），5 分钟K线收盘'),
    'Building range': ('Муж үүсч байна', '区间形成中'),
    'Watching': ('Ажиглаж байна', '盯盘中'),
    'Broke out up': ('Дээш эвдэрсэн', '向上突破'),
    'Broke out down': ('Доош эвдэрсэн', '向下突破'),
    'No breakout (window closed)': ('Эвдрэл болоогүй (хугацаа дууссан)', '未突破（窗口已关闭）'),
    'since': ('эхэлсэн', '自'),
    'low': ('доод', '低'),
    'open': ('нээлт', '开盘'),
    'London': ('Лондон', '伦敦'),
    'New York': ('Нью-Йорк', '纽约'),
    'Range high': ('Мужийн дээд', '区间高点'),
    'Range low': ('Мужийн доод', '区间低点'),
    'Replay this breakout 10,000×': ('Энэ эвдрэлийг 10,000 удаа давтах', '把这次突破重放 10,000 次'),
    'How the 10,000 replays end': ('10,000 давталт хэрхэн дуусдаг', '10,000 次重放的结局'),
    'risk:reward': ('эрсдэл:ашиг', '风险回报'),
    'No session data yet.': ('Сешний өгөгдөл алга.', '暂无时段数据。'),
    'Tested on 2 years of gold and EURUSD with costs: this breakout broke even or lost (profit factor 0.76-1.02). Use it to watch the open, not as a signal on its own.': ('Алт ба EURUSD дээр 2 жил зардалтай туршсан: энэ эвдрэл тэнцсэн эсвэл алдагдалтай (PF 0.76-1.02). Нээлтийг ажиглахад ашигла, дангаараа дохио биш.', '在黄金和 EURUSD 上用 2 年数据（含成本）测试：这种突破持平或亏损（盈利因子 0.76-1.02）。用来盯开盘，不要单独当信号。'),
    'Strength zones': ('Хүчний бүсүүд', '强度区域'),
    'BUY ZONE': ('АВАХ БҮС', '买入区'),
    'SELL ZONE': ('ЗАРАХ БҮС', '卖出区'),
    'reactions': ('хариу үйлдэл', '次反应'),
    'Strength': ('Хүч', '强度'),
    'No active zone': ('Идэвхтэй бүс алга', '无有效区域'),
    'VERY STRONG': ('МАШ ХҮЧТЭЙ', '非常强'),
    'STRONG': ('ХҮЧТЭЙ', '强'),
    'MODERATE': ('ДУНД', '中等'),
    'WEAK': ('СУЛ', '弱'),
    'UP': ('ӨСӨХ', '上升'),
    'DOWN': ('БУУРАХ', '下降'),
    'SIDEWAYS': ('ХАЖУУ', '横盘'),
    'BUY': ('АВАХ', '买入'),
    'SELL': ('ЗАРАХ', '卖出'),
    'Trend': ('Чиг', '趋势'),
    'Price': ('Үнэ', '价格'),
    'Nearest': ('Хамгийн ойр', '最近'),
    'inside the buy zone': ('авах бүсийн дотор', '在买入区内'),
    'inside the sell zone': ('зарах бүсийн дотор', '在卖出区内'),
    'near the buy zone': ('авах бүсийн ойролцоо', '接近买入区'),
    'near the sell zone': ('зарах бүсийн ойролцоо', '接近卖出区'),
    'between zones': ('бүсүүдийн хооронд', '在区域之间'),
    '{side} zone, {d} ATR away': ('{side} бүс, {d} ATR зайтай', '{side}区，距离 {d} ATR'),
    'Zones = places where price turned several times before. Tested 10 years: price reacted at them no more often than at random levels, so use them as a map and for targets, not as signals.': ('Бүс = үнэ өмнө нь хэд хэдэн удаа эргэсэн газар. 10 жил туршсан: үнэ эдгээр бүсэд санамсаргүй түвшнээс илүү хариу үзүүлээгүй тул газрын зураг, зорилт болгон ашигла, дохио болгож бүү ашигла.', '区域 = 价格之前多次掉头的地方。10 年测试：价格在这些区域的反应并不比在随机价位更多，所以把它当作地图和目标位，而不是信号。'),
    'Gold trend pullback': ('Алтны трендийн буцалт', '黄金趋势回调'),
    "Gold's daily trend is up (above its 50-day average) and the 4-hour trend agrees": ('Алтны өдрийн тренд өсөх (50 өдрийн дунджаас дээш), 4 цагийн тренд ч мөн өсөх', '黄金日线趋势向上（高于 50 日均线），4 小时趋势也一致'),
    'Only during London / New York hours, when gold moves for real': ('Зөвхөн Лондон / Нью-Йоркийн цагаар — алт жинхэнэ хөдөлдөг үед', '只在伦敦 / 纽约时段——黄金真正活跃的时候'),
    '4H uptrend (close > EMA50 > EMA200)': ('4 цагийн өсөх тренд (хаалт > EMA50 > EMA200)', '4 小时上升趋势（收盘 > EMA50 > EMA200）'),
    'London / New York hours (07-17 UTC)': ('Лондон / Нью-Йоркийн цаг (07-17 UTC)', '伦敦 / 纽约时段（07-17 UTC）'),
    '10-year proof: what these signals would have done to your account': ('10 жилийн баталгаа: эдгээр дохио таны дансыг яаж өсгөх байсан бэ', '10 年验证：这些信号会让你的账户变成多少'),
    'Signals to include': ('Оруулах дохионууд', '包含的信号'),
    'Start': ('Эхлэл', '起始'),
    'After {y} years': ('{y} жилийн дараа', '{y} 年后'),
    'Per year': ('Жилд', '每年'),
    'Worst drop': ('Хамгийн их уналт', '最大回撤'),
    'All picked signals': ('Сонгосон бүх дохио', '所选全部信号'),
    'Your balance is below what the 0.01 minimum lot needs for {r}% risk on every signal (about ${b}). The real risk per trade will be higher than the slider says.': ('Таны данс 0.01 хамгийн бага лотоор дохио бүрт {r}% эрсдэл гаргахад хүрэлцэхгүй (ойролцоогоор ${b} хэрэгтэй). Бодит эрсдэл гулсуурын тооноос их байна.', '你的余额不足以在 0.01 最小手数下让每个信号只冒 {r}% 风险（约需 ${b}）。实际每笔风险会高于滑块显示的数值。'),
    'Real 10-year history (Dukascopy prices, Pepperstone Razor costs), every closed trade of the picked signals, the balance compounded at your risk % per trade. Change Balance and Risk in the sidebar. This is a test of the past, not a promise: real trading adds slippage, missed signals and emotions.': ('Бодит 10 жилийн түүх (Dukascopy үнэ, Pepperstone Razor зардал), сонгосон дохионуудын хаагдсан бүх арилжаа, данс арилжаа бүрт таны эрсдэлийн хувиар нийлмэлээр өссөн. Данс ба эрсдэлээ хажуугийн самбараас өөрчил. Энэ бол өнгөрсний тест, амлалт биш: бодит арилжаанд гулсалт, алдсан дохио, сэтгэл хөдлөл нэмэгдэнэ.', '真实 10 年历史（Dukascopy 价格，Pepperstone Razor 成本），所选信号的每笔已平仓交易，余额按你的每笔风险 % 复利增长。在侧栏修改余额和风险。这是对过去的测试，不是承诺：实盘还有滑点、错过的信号和情绪。'),
    'Recent signals (live data) and how they ended': ('Сүүлийн дохионууд (бодит өгөгдөл) ба үр дүн', '最近的信号（实时数据）及结果'),
    'Closed: {w} won, {l} lost, total {r}R ({u})': ('Хаагдсан: {w} ашиг, {l} алдагдал, нийт {r}R ({u})', '已平仓：{w} 盈，{l} 亏，合计 {r}R（{u}）'),
    'Same rules as the live signals, on the candles loaded now (about the last 6 months). $ = your balance x risk % x R.': ('Бодит дохиотой ижил дүрэм, одоо ачаалсан лаан дээр (сүүлийн ~6 сар). $ = данс x эрсдэл % x R.', '与实时信号相同的规则，基于当前加载的 K 线（约最近 6 个月）。$ = 余额 x 风险 % x R。'),
    'Risk on trend signals %': ('Трендийн дохионы эрсдэл %', '趋势信号风险 %'),
    'Risk on high-accuracy signals %': ('Өндөр нарийвчлалтай дохионы эрсдэл %', '高胜率信号风险 %'),
    'Gold trend pullback: wins about 1 in 3, but the wins are big (trailing stop).': ('Алтны трендийн буцалт: 3 удаад ~1 ашигтай, гэхдээ ашиг нь том (дагадаг стоп).', '黄金趋势回调：约 3 笔赢 1 笔，但盈利很大（移动止损）。'),
    'Wins 83-91% of trades with small wins; in 10 years the worst run of losses was 1-4.4 risk units, so these can carry more risk.': ('Арилжааны 83-91% ашигтай, ашиг нь жижиг; 10 жилд хамгийн муу алдагдлын цуваа 1-4.4 эрсдэлийн нэгж байсан тул илүү эрсдэл даана.', '83-91% 的交易盈利但盈利较小；10 年里最差的连续亏损只有 1-4.4 个风险单位，所以可以承担更多风险。'),
    'Your balance is below what the 0.01 minimum lot needs for this risk on every signal (about ${b}). The real risk per trade will be higher than the sliders say.': ('Таны данс 0.01 хамгийн бага лотоор дохио бүрт энэ эрсдэлийг гаргахад хүрэлцэхгүй (ойролцоогоор ${b} хэрэгтэй). Бодит эрсдэл гулсуурын тооноос их байна.', '你的余额不足以在 0.01 最小手数下让每个信号保持这个风险（约需 ${b}）。实际每笔风险会高于滑块显示的数值。'),
    'Real 10-year history (Dukascopy prices, Pepperstone Razor costs), every closed trade of the picked signals, the balance compounded at the risk % above. Change the Balance in the sidebar. This is a test of the past, not a promise: real trading adds slippage, missed signals and emotions.': ('Бодит 10 жилийн түүх (Dukascopy үнэ, Pepperstone Razor зардал), сонгосон дохионуудын хаагдсан бүх арилжаа, данс дээрх эрсдэлийн хувиар нийлмэлээр өссөн. Дансаа хажуугийн самбараас өөрчил. Энэ бол өнгөрсний тест, амлалт биш: бодит арилжаанд гулсалт, алдсан дохио, сэтгэл хөдлөл нэмэгдэнэ.', '真实 10 年历史（Dukascopy 价格，Pepperstone Razor 成本），所选信号的每笔已平仓交易，余额按上面的风险 % 复利增长。在侧栏修改余额。这是对过去的测试，不是承诺：实盘还有滑点、错过的信号和情绪。'),
    'Bitcoin 7-day breakout': ('Биткойны 7 хоногийн нэвтрэлт', '比特币 7 日突破'),
    "Bitcoin's daily trend and 4-hour trend point the same way": ('Биткойны өдрийн ба 4 цагийн тренд нэг чиглэлтэй', '比特币日线和 4 小时趋势方向一致'),
    'Price closed beyond its 7-day high (buy) or 7-day low (sell) - a breakout in the trend direction': ('Үнэ 7 хоногийн дээд цэгээс дээш (авах) эсвэл доод цэгээс доош (зарах) хаагдсан — трендийн чиглэлд нэвтрэлт', '价格收于 7 日最高价之上（买）或 7 日最低价之下（卖）——顺势突破'),
    'Bitcoin and gold almost never move together, so this adds profit without adding the same risk': ('Биткойн ба алт бараг хамт хөдөлдөггүй тул энэ нь ижил эрсдэл нэмэлгүйгээр ашиг нэмнэ', '比特币和黄金几乎不同步，所以它增加利润而不叠加同样的风险'),
    'No fixed target: the stop follows price 4×ATR behind, so big crypto moves are kept': ('Тогтмол зорилтгүй: стоп үнийг 4×ATR зайтай дагана, тиймээс крипто том хөдөлгөөнийг барина', '没有固定目标：止损在价格后方 4×ATR 跟随，保住加密货币的大行情'),
    'Daily trend clear (50-day average)': ('Өдрийн тренд тодорхой (50 өдрийн дундаж)', '日线趋势明确（50 日均线）'),
    '4H trend agrees': ('4 цагийн тренд нийцэж байна', '4 小时趋势一致'),
    'Closed above the 7-day high': ('7 хоногийн дээд цэгээс дээш хаагдсан', '收于 7 日最高价之上'),
    'Closed below the 7-day low': ('7 хоногийн доод цэгээс доош хаагдсан', '收于 7 日最低价之下'),
    'Use the tested mix: 1% on trend signals, 2% on high-accuracy signals': ('Туршсан хослол: трендийн дохионд 1%, өндөр нарийвчлалтай дохионд 2%', '使用测试组合：趋势信号 1%，高胜率信号 2%'),
    'In the 10-year tests this gave the best profit for the drawdown. More risk = more profit AND deeper drops.': ('10 жилийн тестэд энэ нь уналттай харьцуулахад хамгийн сайн ашиг өгсөн. Их эрсдэл = их ашиг БА гүн уналт.', '在 10 年测试中，这个组合的收益/回撤比最好。风险越大 = 利润越多，回撤也越深。'),
    'Bad-luck check (same trades, 500 random orders): in 1 case out of 20 the worst drop reaches {d}%; the ending balance lands between ${a} and ${b} in 9 cases out of 10.': ('Азгүй тохиолдлын шалгалт (ижил арилжаа, 500 санамсаргүй дараалал): 20 тохиолдлын 1-д хамгийн их уналт {d}% хүрнэ; 10 тохиолдлын 9-д эцсийн данс ${a}-аас ${b}-ийн хооронд байна.', '坏运气检验（同样的交易，500 种随机顺序）：每 20 次中有 1 次最大回撤达到 {d}%；10 次中有 9 次最终余额在 ${a} 到 ${b} 之间。'),
    "Lots (size 100000)": ("Лот (хэмжээ 100000)", "手数（每手 100000）"),
    "Your trade size, like the TradingView order panel. 0 = let the app size it from your balance and risk %.":
        ("Таны арилжааны хэмжээ, TradingView-ийн захиалгын самбар шиг. 0 = үлдэгдэл ба эрсдэлийн %-аас апп тооцно.",
         "你的交易手数，和 TradingView 下单面板一样。0 = 由应用根据余额和风险 % 计算。"),
    "Pip value: {v} USD": ("Пипсийн үнэ: {v} USD", "每点价值：{v} USD"),
    "Lot size: auto from balance and risk %": ("Лот: үлдэгдэл ба эрсдэлийн %-аас автоматаар", "手数：按余额和风险 % 自动计算"),
    "Pip value shown in the signal panel": ("Пипсийн үнэ дохионы самбарт харагдана", "每点价值见信号面板"),
    "pip value {pv} USD": ("пипсийн үнэ {pv} USD", "每点 {pv} USD"),
    "Live chart": ("Шууд график", "实时图表"), "Update every (seconds)": ("Шинэчлэх давтамж (секунд)", "刷新间隔（秒）"),
    "Price and the forming candle update this often. Full candle history reloads every 25 s. For true tick-by-tick prices choose the MT5 source (Pepperstone MT5 terminal).":
        ("Үнэ ба одоо үүсэж буй лаа энэ давтамжаар шинэчлэгдэнэ. Бүх түүх 25 секунд тутам. Жинхэнэ тик үнэ авахыг хүсвэл MT5 эх сурвалжийг сонго.",
         "价格和正在形成的K线按此间隔刷新，完整历史每 25 秒重新加载。要逐笔报价请选择 MT5 数据源（Pepperstone MT5 终端）。"),
    "TP1 HIT": ("TP1 ХҮРСЭН", "TP1 已达成"), "SL moved to breakeven": ("Стоп орлтын үнэ рүү шилжсэн", "止损已移至保本"),
    "close half, SL to breakeven": ("талыг хаа, стопыг орлтын үнэ рүү", "平仓一半，止损移至保本"),
    "exit on the bounce": ("сэргэлт дээр гар", "反弹时离场"), "Stop now": ("Одоогийн стоп", "当前止损"),
    "Last signal: {side} at {e} on {t} UTC → {r}R": ("Сүүлийн дохио: {side} {e} · {t} UTC → {r}R", "上一个信号：{side} {e} · {t} UTC → {r}R"),
    "{sym} TP1 hit - close half and move the stop to breakeven": ("{sym} TP1 хүрлээ - талыг хааж, стопыг орлтын үнэ рүү шилжүүл",
                                                                  "{sym} 到达 TP1 - 平仓一半并把止损移至保本"),
    "Stop 1.5×ATR below entry. TP1 at 1:1 - close half and move the stop to breakeven. TP2: close the rest when a candle closes back above the 5-period average (the bounce). Signals come from the H1 chart and show on any chart.":
        ("Стоп орлтоос 1.5×ATR доор. TP1 1:1 - талыг хааж стопыг орлтын үнэ рүү шилжүүл. TP2: лаа 5-ийн дунджаас дээш хаагдахад үлдсэнийг хаа (сэргэлт). Дохио H1 графикаас ирж, бүх график дээр харагдана.",
         "止损在入场价下方 1.5×ATR。TP1 为 1:1 - 平仓一半并把止损移至保本。TP2：K线收回 5 周期均线上方（反弹）时平掉剩余仓位。信号来自 H1 图表，在任何周期图上都会显示。"),
    "DeepSeek suggests caution on this entry - read the analysis below.":
        ("DeepSeek энэ оролтод болгоомжлохыг зөвлөж байна — доорх шинжилгээг уншина уу.", "DeepSeek 建议谨慎入场——请阅读下方分析。"),
    "{n} trades · win {w}% · {r}R per trade · PF {pf} · worst drawdown {dd}R ({tf})":
        ("{n} арилжаа · ялалт {w}% · арилжаа тутам {r}R · PF {pf} · хамгийн их уналт {dd}R ({tf})",
         "{n} 笔 · 胜率 {w}% · 每笔 {r}R · 盈亏比 {pf} · 最大回撤 {dd}R（{tf}）"),
    "WIN RATE": ("ЯЛАЛТ", "胜率"), "Exit plan": ("Гарах төлөвлөгөө", "离场计划"),
    "No fixed target: the stop trails 3×ATR behind the best price, so winners can run and losers stay small.":
        ("Тогтсон зорилтгүй: стоп хамгийн сайн үнээс 3×ATR-ийн зайтай дагана — ашигтай арилжаа урт явж, алдагдал жижиг үлдэнэ.",
         "不设固定目标：止损跟随最优价格 3×ATR，让盈利奔跑、亏损保持很小。"),
    "Tested on this market": ("Энэ зах зээл дээр туршсан", "该品种回测"), "AI view": ("AI-ийн дүгнэлт", "AI 观点"),
    "Strategy profitable on this market (tested)": ("Стратеги энэ зах зээлд ашигтай (туршсан)", "策略在该品种盈利（回测）"),
    "no": ("үгүй", "否"),
    "4H trend clear (EMA50 vs EMA200)": ("4H чиг тодорхой (EMA50 ба EMA200)", "4H 趋势明确（EMA50 vs EMA200）"),
    "Active session (07-17 UTC)": ("Идэвхтэй сесс (07-17 UTC)", "活跃时段（07-17 UTC）"),
    "Trending market (ADX ≥ 20)": ("Чигтэй зах зээл (ADX ≥ 20)", "趋势行情（ADX ≥ 20）"),
    "Structure holds (EMA20 vs EMA50)": ("Бүтэц хадгалагдаж байна (EMA20 ба EMA50)", "结构保持（EMA20 vs EMA50）"),
    "Pulled back to EMA20": ("EMA20 руу буцсан", "已回踩 EMA20"), "Confirmation candle": ("Баталгаажуулах лаа", "确认K线"),
    "Stop within 3×ATR": ("Стоп 3×ATR дотор", "止损在 3×ATR 内"),
    "{s} on this chart: {n} trades · won {w} · lost {l} · total {t}R":
        ("{s} энэ график дээр: {n} арилжаа · ✓{w} · ✗{l} · нийт {t}R", "{s} 本图：{n} 笔 · 盈 {w} · 亏 {l} · 合计 {t}R"),
    "Recent trades of this strategy": ("Энэ стратегийн сүүлийн арилжаанууд", "该策略近期交易"),
    "Time": ("Цаг", "时间"), "Exit": ("Гарсан", "离场"),
    "QUALITY": ("ЧАНАР", "质量"), "Quality": ("Чанар", "质量"), "Strong": ("Хүчтэй", "强"), "Weak": ("Сул", "弱"),
    "No edge": ("Давуу талгүй", "无优势"),
    "High win-rate mode (70%+ tested)": ("Өндөр ялалтын горим (70%+ туршсан)", "高胜率模式（回测 70%+）"),
    "Connors Double-7 dip-buy (high win rate)": ("Connors Double-7 уналтад авах (өндөр ялалт)", "Connors Double-7 逢低买入（高胜率）"),
    "Connors RSI(2) dip-buy (high win rate)": ("Connors RSI(2) уналтад авах (өндөр ялалт)", "Connors RSI(2) 逢低买入（高胜率）"),
    "Signal v26 + 0.5R target (high win rate)": ("Signal v26 + 0.5R зорилт (өндөр ялалт)", "世界最强信号 v26 + 0.5R 目标（高胜率）"),
    "Price is below its 200-period average - dip-buying is paused until the uptrend returns.":
        ("Ханш 200 үеийн дунджаас доор — өсөх чиг сэргэх хүртэл уналтад авахыг зогсооно.", "价格低于 200 周期均线——上升趋势恢复前暂停逢低买入。"),
    "Uptrend confirmed. Waiting for a sharp dip ({what}) to buy.": ("Өсөх чиг баталгаажсан. Худалдан авах огцом уналтыг ({what}) хүлээж байна.", "上升趋势确认。等待急跌（{what}）买入。"),
    "close at a 7-period low": ("7 үеийн хамгийн доод хаалт", "收盘创 7 周期新低"), "RSI(2) below 5": ("RSI(2) 5-аас доош", "RSI(2) 低于 5"),
    "Uptrend (above 200-period average)": ("Өсөх чиг (200 үеийн дунджаас дээр)", "上升趋势（高于 200 周期均线）"),
    "Sharp dip signal": ("Огцом уналтын дохио", "急跌信号"), "Exit when price closes back above": ("Ханш дээш хаагдвал гарах түвшин", "收盘回到此价位上方离场"),
    "Sell the bounce: exit when price closes back above the 5-period average / 7-period high. Safety stop 3×ATR below entry.":
        ("Сэргэлтэд зарна: ханш 5 үеийн дундаж / 7 үеийн дээдээс дээш хаагдахад гарна. Хамгаалалтын стоп орох цэгээс 3×ATR доор.",
         "反弹卖出：收盘回到 5 周期均线 / 7 周期高点上方离场。保护止损在入场下方 3×ATR。"),
    "Fixed target at +0.5R, stop at the signal's stop. Small wins most of the time; that is why the win rate is high.":
        ("+0.5R тогтсон зорилт, стоп дохионы стоп дээр. Ихэнхдээ жижиг ашиг — тиймээс ялалтын хувь өндөр.", "固定 +0.5R 目标，止损为信号止损。多数为小额盈利——这就是胜率高的原因。"),
    "High win-rate mode: {plan} on {tf}. Wins are smaller and more frequent; see the tested numbers on the right.":
        ("Өндөр ялалтын горим: {plan}, {tf} дээр. Ашиг жижиг боловч олон удаа; баруун талын туршилтын тоог үзнэ үү.", "高胜率模式：{plan}，周期 {tf}。盈利更小但更频繁；请看右侧回测数据。"),
    "no tested high win-rate plan for this market": ("энэ зах зээлд туршсан өндөр ялалтын төлөвлөгөө алга", "该品种无通过回测的高胜率方案"),
    "Strict mode (fewer, stronger signals)": ("Хатуу горим (цөөн, хүчтэй дохио)", "严格模式（信号更少更强）"),
    "Skips trades with less than 1R of room to the opposing swing. Tested: big gain on BTCUSD and EURUSD, none on gold, about half the signals.":
        ("Эсрэг талын swing хүртэл 1R-ээс бага зайтай арилжааг алгасна. Туршилт: BTCUSD, EURUSD дээр их ашиг, алтанд ялгаагүй, дохио хагас болно.",
         "跳过距反向波段不足 1R 的交易。回测：BTCUSD、EURUSD 明显提升，黄金无提升，信号约减半。"),
    "Alerts: sound + desktop popup": ("Сануулга: дуу + дэлгэцийн мэдэгдэл", "提醒：声音 + 桌面通知"),
    "Needs 'Live chart refresh' on and this tab open (it can be in the background).":
        ("'Шууд шинэчлэл' асаалттай, энэ таб нээлттэй байх хэрэгтэй (ард байж болно).", "需要开启“实时刷新”并保持此标签页打开（可在后台）。"),
    "🔔 Test alert / allow notifications": ("🔔 Сануулга турших / мэдэгдэл зөвшөөрөх", "🔔 测试提醒 / 允许通知"),
    "{side} {sym} at {e} · stop {s} · {strat}": ("{side} {sym} {e} · стоп {s} · {strat}", "{side} {sym} {e} · 止损 {s} · {strat}"),
    "{sym} trade closed by the trailing stop: {r}R": ("{sym} арилжааг дагах стоп хаалаа: {r}R", "{sym} 交易被移动止损平仓：{r}R"),
    "Test alert": ("Туршилтын сануулга", "测试提醒"),
    "Test alert sent - you should hear an alarm and see a big banner.": ("Туршилт илгээлээ — дуут дохио сонсож, том анхааруулга харагдах ёстой.", "测试已发送——应听到警报并看到大横幅。"),
    "If you hear the alarm and see this banner, alerts work.": ("Дуут дохио сонсож, энэ анхааруулгыг харвал сануулга ажиллаж байна.", "如果听到警报并看到此横幅，提醒正常。"),
    "Alert volume": ("Сануулгын дууны хэмжээ", "提醒音量"),
    "Optional: stop new signals after a daily loss limit or a number of trades.":
        ("Сонголттой: өдрийн алдагдлын хязгаар эсвэл арилжааны тоонд хүрвэл шинэ дохиог зогсооно.", "可选：达到每日亏损上限或交易次数后停止新信号。"),
    "If you hear two beeps and see this popup, alerts work.": ("Дуут дохио сонсож, том анхааруулга харвал сануулга ажиллаж байна.", "如果听到提示音并看到大横幅，提醒正常。"),
    "If you hear two beeps and see this popup, alerts work.": ("Хоёр дуут дохио сонсож, энэ мэдэгдлийг харвал сануулга ажиллаж байна.", "如果听到两声提示音并看到此弹窗，提醒正常。"),
    "Test alert sent - you should hear two beeps.": ("Туршилтын сануулга илгээлээ — хоёр дуут дохио сонсогдох ёстой.", "已发送测试提醒——应能听到两声提示音。"),
    "Daily trend agrees (pro rule)": ("Өдрийн чиг тохирч байна (про дүрэм)", "日线趋势一致（专业规则）"),
    "Not Monday (pro rule)": ("Даваа гараг биш (про дүрэм)", "非周一（专业规则）"),
    "daily trend to agree": ("өдрийн чиг тохирох", "日线趋势一致"),
    "Tuesday (no Monday trades)": ("Мягмар гараг (Даваа гаригт арилжаа хийхгүй)", "周二（周一不交易）"),
    "No fixed target: the stop trails {k}×ATR behind the best price, so winners can run and losers stay small.":
        ("Тогтсон зорилтгүй: стоп хамгийн сайн үнээс {k}×ATR-ийн зайтай дагана — ашигтай арилжаа урт явж, алдагдал жижиг үлдэнэ.",
         "不设固定目标：止损跟随最优价格 {k}×ATR，让盈利奔跑、亏损保持很小。"),
})

SETUPS = {
    "Liquidity sweep reversal": ("Liquidity sweep эргэлт", "流动性扫荡反转"),
    "VWAP pullback with trend": ("Чиг дагасан VWAP pullback", "顺势 VWAP 回踩"),
    "BOS break & retest": ("BOS эвдрэл ба retest", "BOS 突破回踩"),
    "CHoCH break & retest": ("CHoCH эвдрэл ба retest", "CHoCH 突破回踩"),
    "Asian range breakout": ("Азийн хүрээний эвдрэл", "亚盘区间突破"),
    "Fair value gap retest": ("FVG (fair value gap) retest", "公允价值缺口回踩"),
    "Pro Pullback (your indicator)": ("Pro Pullback (таны индикатор)", "Pro Pullback（你的指标）"),
    "Signal v26 (your indicator)": ("Signal v26 (таны индикатор)", "世界最强信号 v26（你的指标）"),
}


def T(text: str, **kw) -> str:
    if _lang != "en" and text in S:
        text = S[text][0 if _lang == "mn" else 1]
    return text.format(**kw) if kw else text


def setup_name(name: str) -> str:
    if _lang == "en" or not name:
        return name or ""
    for en, tr in SETUPS.items():
        if en.lower() in str(name).lower():
            return tr[0 if _lang == "mn" else 1]
    return name


# Engine / risk messages built with numbers: (regex, mn template, zh template)
_DYN = [
    (r"Minimum lot 0\.01 risks ([\d.]+)% of the account \(target ([\d.]+)%\)\.",
     "0.01 доод лот дансны {0}%-ийг эрсдэлд оруулна (зорилт {1}%).", "最小手数 0.01 将承担账户 {0}% 的风险（目标 {1}%）。"),
    (r"Risk above 5% per trade - skip this setup or use a tighter one\.",
     "Нэг арилжааны эрсдэл 5%-аас их — энэ сетапыг алгасах эсвэл илүү нарийн стоп сонгоно уу.", "单笔风险超过 5%——跳过该形态或使用更紧的止损。"),
    (r"Not enough margin: needs \$([\d,.]+), balance \$([\d,.]+)\.",
     "Барьцаа хүрэлцэхгүй: ${0} хэрэгтэй, үлдэгдэл ${1}.", "保证金不足：需要 ${0}，余额 ${1}。"),
    (r"loses in backtest \(([-+\d.]+)R over (\d+) trades\) - no edge",
     "backtest-д алдагдалтай ({0}R, {1} арилжаа) — давуу талгүй", "回测亏损（{0}R，{1} 笔）——无优势"),
    (r"breakeven in backtest \(([-+\d.]+)R\) - no clear edge",
     "backtest-д тэгтэй ойр ({0}R) — тодорхой давуу талгүй", "回测接近保本（{0}R）——无明显优势"),
    (r"not backtested on this market yet - capped at B",
     "энэ зах зээлд backtest хийгээгүй — B хүртэл хязгаарласан", "该品种尚未回测——上限 B"),
    (r"only (\d+) backtest trades - capped at B",
     "backtest-д зөвхөн {0} арилжаа — B хүртэл хязгаарласан", "回测仅 {0} 笔——上限 B"),
    (r"Grade ([ABC+]+) idea - shown as WAIT\. Only A / A\+ setups are traded\.",
     "{0} зэргийн санаа — ХҮЛЭЭХ. Зөвхөн A / A+ сетапаар арилжаална.", "{0} 级机会——显示为观望。只交易 A / A+ 形态。"),
    (r"AI levels rejected \((.*)\) - engine levels shown\.",
     "AI-ийн түвшнийг татгалзсан ({0}) — хөдөлгүүрийн түвшин харуулав.", "AI 价位被拒绝（{0}）——显示引擎价位。"),
    (r"AI answer did not match this market .*",
     "AI-ийн хариулт энэ зах зээлтэй таарахгүй байна — хэрэгсэхгүй, хөдөлгүүрийн дохио харуулав.", "AI 回答与该品种不符——已忽略，显示引擎信号。"),
    (r"Reward:risk to TP1 only ([\d.]+)\.", "TP1 хүртэлх ашиг:эрсдэл ердөө {0}.", "到 TP1 的盈亏比仅 {0}。"),
]


def tr_dyn(text: str) -> str:
    if _lang == "en" or not text:
        return text
    out = str(text)
    for rx, mn, zh in _DYN:
        m = re.search(rx, out)
        if m:
            out = out.replace(m.group(0), (mn if _lang == "mn" else zh).format(*m.groups()))
    return out

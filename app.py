from __future__ import annotations

import json
import re
import secrets
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from bs4 import BeautifulSoup


PAIR = "USD/JPY"
TICKER = "JPY=X"
JST = ZoneInfo("Asia/Tokyo")
APP_DIR = Path(__file__).resolve().parent
CUSTOM_EVENTS_PATH = APP_DIR / "events_usdjpy.csv"
NOTIFICATION_CONFIG_PATH = APP_DIR / "notification_settings.json"
NOTIFICATION_STATE_PATH = APP_DIR / "notification_state.json"
NTFY_SERVER = "https://ntfy.sh"
DEFAULT_DASHBOARD_URL = "http://localhost:8501"
BLS_CALENDAR_URL = "https://www.bls.gov/schedule/news_release/bls.ics"


@dataclass
class MarketRegime:
    name: str
    bias: str
    score: int
    adx: float
    bb_width: float
    bb_rank: float
    ema_slope: float
    reasons: list[str]
    warnings: list[str]


@dataclass
class MacroContext:
    name: str
    bias: str
    score: int
    ten_year: float | None
    two_year: float | None
    ten_year_5d: float | None
    ten_year_20d: float | None
    last_date: date | None
    reasons: list[str]
    warnings: list[str]


@dataclass
class EventItem:
    event_date: date
    title: str
    source: str
    impact: str


@dataclass
class EventRisk:
    level: str
    title: str
    score_cap: int | None
    items: list[str]
    next_events: list[EventItem]
    warnings: list[str]


@dataclass
class Setup:
    direction: str
    bias: str
    score: int
    entry_low: float
    entry_high: float
    stop: float
    target_1: float
    target_2: float
    support: float
    resistance: float
    atr: float
    reasons: list[str]
    warnings: list[str]


@dataclass
class AnalysisResult:
    hourly: pd.DataFrame
    h4: pd.DataFrame
    daily: pd.DataFrame
    treasury: pd.DataFrame
    events: list[EventItem]
    regime: MarketRegime
    macro: MacroContext
    event_risk: EventRisk
    setup: Setup
    current_price: float
    latest_time: object


@dataclass
class BacktestTrade:
    signal_time: object
    entry_time: object
    exit_time: object
    side: str
    score: int
    entry: float
    stop: float
    target: float
    exit_price: float
    result: str
    pips: float
    r_multiple: float


@dataclass
class BacktestResult:
    trades: list[BacktestTrade]
    skipped_signals: int
    checked_signals: int
    win_rate: float
    total_r: float
    average_r: float
    profit_factor: float
    max_drawdown_r: float
    max_losing_streak: int
    suggested_threshold: int | None


st.set_page_config(
    page_title="USD/JPY Signal Desk",
    page_icon="FX",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.4rem; padding-bottom: 2rem; }
      [data-testid="stMetric"] {
        border: 1px solid #d9dee7;
        border-radius: 8px;
        padding: 12px 14px;
        background: #ffffff;
      }
      [data-testid="stMetricLabel"] { color: #465261; }
      .signal-box {
        border: 1px solid #d9dee7;
        border-radius: 8px;
        padding: 16px 18px;
        background: #ffffff;
        min-height: 138px;
      }
      .signal-title {
        font-size: 0.9rem;
        color: #465261;
        margin-bottom: 0.4rem;
      }
      .signal-value {
        font-size: 1.42rem;
        line-height: 1.35;
        font-weight: 700;
        color: #151a20;
      }
      .muted { color: #687483; font-size: 0.92rem; }
      .ok { color: #107a53; font-weight: 700; }
      .bad { color: #b42318; font-weight: 700; }
      .wait { color: #7a4d00; font-weight: 700; }
    </style>
    """,
    unsafe_allow_html=True,
)


def clean_download(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    data = raw.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data = data.rename(columns={c: str(c).title() for c in data.columns})
    expected = ["Open", "High", "Low", "Close"]
    data = data[[c for c in expected if c in data.columns]].dropna()
    data = data[~data.index.duplicated(keep="last")]
    return data


@st.cache_data(ttl=15 * 60, show_spinner=False)
def fetch_prices(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly = yf.download(
        ticker,
        period="90d",
        interval="60m",
        progress=False,
        auto_adjust=False,
        prepost=True,
        threads=False,
    )
    daily = yf.download(
        ticker,
        period="2y",
        interval="1d",
        progress=False,
        auto_adjust=False,
        prepost=True,
        threads=False,
    )
    return clean_download(hourly), clean_download(daily)


@st.cache_data(ttl=15 * 60, show_spinner=False)
def fetch_backtest_prices(ticker: str, period: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly = yf.download(
        ticker,
        period=period,
        interval="60m",
        progress=False,
        auto_adjust=False,
        prepost=True,
        threads=False,
    )
    daily = yf.download(
        ticker,
        period="2y",
        interval="1d",
        progress=False,
        auto_adjust=False,
        prepost=True,
        threads=False,
    )
    return clean_download(hourly), clean_download(daily)


def parse_float(text: str | None) -> float | None:
    if text is None or text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def fetch_treasury_yields() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    current_year = datetime.now(JST).year
    years = [current_year - 1, current_year]
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
        "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
    }

    for year in years:
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/pages/xml?data=daily_treasury_yield_curve"
            f"&field_tdr_date_value={year}"
        )
        response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        root = ET.fromstring(response.text)
        for entry in root.findall("atom:entry", ns):
            props = entry.find(".//m:properties", ns)
            if props is None:
                continue
            item = {child.tag.split("}", 1)[-1]: child.text for child in props}
            day_text = item.get("NEW_DATE")
            if not day_text:
                continue
            rows.append(
                {
                    "date": pd.to_datetime(day_text).date(),
                    "2Y": parse_float(item.get("BC_2YEAR")),
                    "10Y": parse_float(item.get("BC_10YEAR")),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["date", "2Y", "10Y"])
    data = pd.DataFrame(rows).dropna().drop_duplicates("date").sort_values("date")
    return data.reset_index(drop=True)


def build_macro_context(yields: pd.DataFrame, current_date: date | None = None) -> MacroContext:
    if yields.empty or len(yields) < 25:
        return MacroContext(
            name="米金利データなし",
            bias="neutral",
            score=0,
            ten_year=None,
            two_year=None,
            ten_year_5d=None,
            ten_year_20d=None,
            last_date=None,
            reasons=[],
            warnings=["米金利データを取得できなかったため、金利フィルターは未反映"],
        )

    latest = yields.iloc[-1]
    ten_year = float(latest["10Y"])
    two_year = float(latest["2Y"])
    last_date = latest["date"]
    ten_year_5d = ten_year - float(yields.iloc[-6]["10Y"])
    ten_year_20d = ten_year - float(yields.iloc[-21]["10Y"])

    reasons: list[str] = []
    warnings: list[str] = []
    score = 0
    bias = "neutral"
    name = "米金利は中立"

    if ten_year_5d >= 0.08 and ten_year_20d >= 0:
        bias = "buy"
        score = 14
        name = "米金利上昇"
        reasons.append("米10年債利回りが短期的に上昇し、ドル円の買い材料")
    elif ten_year_5d <= -0.08 and ten_year_20d <= 0:
        bias = "sell"
        score = 14
        name = "米金利低下"
        reasons.append("米10年債利回りが短期的に低下し、ドル円の売り材料")
    elif ten_year_20d >= 0.15:
        bias = "buy"
        score = 8
        name = "米金利じり高"
        reasons.append("米10年債利回りの20営業日変化が上向き")
    elif ten_year_20d <= -0.15:
        bias = "sell"
        score = 8
        name = "米金利じり安"
        reasons.append("米10年債利回りの20営業日変化が下向き")
    else:
        reasons.append("米10年債利回りは明確な追い風/向かい風なし")

    reference_date = current_date or datetime.now(JST).date()
    if isinstance(last_date, date) and (reference_date - last_date).days >= 7:
        warnings.append("米金利データの最終日が古いため、参考度は低め")

    return MacroContext(
        name=name,
        bias=bias,
        score=score,
        ten_year=ten_year,
        two_year=two_year,
        ten_year_5d=ten_year_5d,
        ten_year_20d=ten_year_20d,
        last_date=last_date,
        reasons=reasons,
        warnings=warnings,
    )


def with_indicators(data: pd.DataFrame) -> pd.DataFrame:
    out = data.copy()
    close = out["Close"]
    high = out["High"]
    low = out["Low"]

    out["EMA20"] = close.ewm(span=20, adjust=False).mean()
    out["SMA50"] = close.rolling(50).mean()
    out["SMA200"] = close.rolling(200).mean()

    out["BB_MID"] = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    out["BB_UPPER"] = out["BB_MID"] + bb_std * 2
    out["BB_LOWER"] = out["BB_MID"] - bb_std * 2
    out["BB_WIDTH"] = ((out["BB_UPPER"] - out["BB_LOWER"]) / out["BB_MID"]) * 100

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out["RSI14"] = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["MACD"] = ema12 - ema26
    out["MACD_SIGNAL"] = out["MACD"].ewm(span=9, adjust=False).mean()

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["ATR14"] = tr.rolling(14).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=out.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=out.index,
    )
    atr_wilder = tr.ewm(alpha=1 / 14, adjust=False).mean()
    out["PLUS_DI14"] = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_wilder
    out["MINUS_DI14"] = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_wilder
    dx = (
        (out["PLUS_DI14"] - out["MINUS_DI14"]).abs()
        / (out["PLUS_DI14"] + out["MINUS_DI14"]).replace(0, np.nan)
    ) * 100
    out["ADX14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()

    return out.dropna()


def to_4h(hourly: pd.DataFrame) -> pd.DataFrame:
    return (
        hourly.resample("4h")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        .dropna()
    )


def fmt_price(value: float, pair: str) -> str:
    decimals = 3 if "JPY" in pair else 5
    return f"{value:,.{decimals}f}"


def fmt_signed(value: float | None, suffix: str = "") -> str:
    if value is None or not np.isfinite(value):
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}{suffix}"


def pct_distance(price: float, level: float) -> float:
    if not price:
        return 0.0
    return abs(price - level) / price


def percentile_rank(series: pd.Series, value: float) -> float:
    clean = series.dropna()
    if clean.empty:
        return 50.0
    return float((clean <= value).mean() * 100)


def analyze_regime(h4: pd.DataFrame) -> MarketRegime:
    latest = h4.iloc[-1]
    past = h4.iloc[-9] if len(h4) >= 9 else h4.iloc[0]
    adx = float(latest["ADX14"])
    bb_width = float(latest["BB_WIDTH"])
    bb_rank = percentile_rank(h4["BB_WIDTH"].tail(160), bb_width)
    ema_slope = (float(latest["EMA20"]) - float(past["EMA20"])) / float(latest["Close"]) * 100
    plus_di = float(latest["PLUS_DI14"])
    minus_di = float(latest["MINUS_DI14"])

    reasons: list[str] = []
    warnings: list[str] = []
    score = 0
    bias = "neutral"
    name = "中立"

    if adx >= 25 and abs(ema_slope) >= 0.18:
        if ema_slope > 0 and plus_di > minus_di:
            name = "上昇トレンド"
            bias = "buy"
            score = 16
            reasons.append("ADXが高く、4時間足の上昇トレンドが出ている")
        elif ema_slope < 0 and minus_di > plus_di:
            name = "下降トレンド"
            bias = "sell"
            score = 16
            reasons.append("ADXが高く、4時間足の下降トレンドが出ている")
        else:
            name = "方向確認中"
            reasons.append("ADXは高いが、移動平均とDIの方向が揃いきっていない")
    elif adx < 18 and bb_rank < 35:
        name = "レンジ/収縮"
        score = -6
        warnings.append("ADXとボリンジャーバンド幅が低く、ブレイク待ちになりやすい")
    elif bb_rank >= 80:
        name = "ボラ拡大"
        reasons.append("ボリンジャーバンド幅が大きく、値動きは出ている")
        if ema_slope > 0:
            bias = "buy"
            score = 8
        elif ema_slope < 0:
            bias = "sell"
            score = 8
    else:
        reasons.append("相場環境は中立で、価格帯の反応待ち")

    return MarketRegime(
        name=name,
        bias=bias,
        score=score,
        adx=adx,
        bb_width=bb_width,
        bb_rank=bb_rank,
        ema_slope=ema_slope,
        reasons=reasons,
        warnings=warnings,
    )


def parse_month_day(text: str, year: int) -> date | None:
    months = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    current_month: int | None = None
    last_day: int | None = None
    pattern = re.compile(r"(?:(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s*)?(\d{1,2})", re.I)
    for match in pattern.finditer(text):
        month_text, day_text = match.groups()
        if month_text:
            current_month = months[month_text.lower().rstrip(".")]
        if current_month is not None:
            last_day = int(day_text)
    if current_month is None or last_day is None:
        return None
    try:
        return date(year, current_month, last_day)
    except ValueError:
        return None


def parse_fomc_events(year: int) -> list[EventItem]:
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    html = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).text
    soup = BeautifulSoup(html, "html.parser")
    events: list[EventItem] = []

    for heading in soup.find_all(["h4", "h3"]):
        if f"{year} FOMC Meetings" not in heading.get_text(" ", strip=True):
            continue
        panel = heading.find_parent("div", class_="panel")
        if panel is None:
            continue
        for row in panel.select(".fomc-meeting"):
            month_el = row.select_one(".fomc-meeting__month")
            date_el = row.select_one(".fomc-meeting__date")
            if not month_el or not date_el:
                continue
            day = parse_month_day(f"{month_el.get_text(' ', strip=True)} {date_el.get_text(' ', strip=True)}", year)
            if day:
                events.append(EventItem(day, "FOMC政策発表", "Federal Reserve", "high"))
    return events


def parse_boj_events(year: int) -> list[EventItem]:
    url = "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"
    html = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).text
    soup = BeautifulSoup(html, "html.parser")
    events: list[EventItem] = []

    table = soup.find("table")
    if table is None:
        return events
    for row in table.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if not cells or "Date of MPM" in cells[0] or "Outlook Report" in cells[0]:
            continue
        meeting_date_text = re.sub(r"\[.*$", "", cells[0]).strip()
        day = parse_month_day(meeting_date_text, year)
        if day:
            events.append(EventItem(day, "日銀金融政策決定会合", "Bank of Japan", "high"))
    return events


def unfold_ics_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def parse_ics_date(line: str) -> date | None:
    if ":" not in line:
        return None
    value = line.split(":", 1)[1].strip()
    if len(value) < 8:
        return None
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


def parse_bls_events() -> list[EventItem]:
    response = requests.get(BLS_CALENDAR_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    text = response.text
    lines = unfold_ics_lines(text)
    events: list[EventItem] = []
    current: dict[str, str] = {}
    watched = {
        "Employment Situation": "米雇用統計",
        "Consumer Price Index": "米CPI",
        "Producer Price Index": "米PPI",
        "Real Earnings": "米実質賃金",
    }

    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            title = current.get("SUMMARY", "")
            day = parse_ics_date(current.get("DTSTART", ""))
            if day:
                for keyword, label in watched.items():
                    if keyword in title:
                        events.append(EventItem(day, label, "BLS", "high"))
                        break
            current = {}
            continue
        if line.startswith("SUMMARY"):
            current["SUMMARY"] = line.split(":", 1)[1] if ":" in line else ""
        elif line.startswith("DTSTART"):
            current["DTSTART"] = line

    return events


def load_custom_events() -> list[EventItem]:
    if not CUSTOM_EVENTS_PATH.exists():
        return []
    try:
        data = pd.read_csv(CUSTOM_EVENTS_PATH, comment="#")
    except Exception:
        return []
    events: list[EventItem] = []
    for _, row in data.dropna(subset=["date", "title"]).iterrows():
        try:
            day = pd.to_datetime(row["date"]).date()
        except Exception:
            continue
        events.append(
            EventItem(
                event_date=day,
                title=str(row["title"]),
                source="manual",
                impact=str(row.get("impact", "high")),
            )
        )
    return events


@st.cache_data(ttl=12 * 60 * 60, show_spinner=False)
def fetch_policy_events() -> list[EventItem]:
    year = datetime.now(JST).year
    events: list[EventItem] = []
    try:
        events.extend(parse_fomc_events(year))
        events.extend(parse_fomc_events(year + 1))
    except Exception:
        pass
    try:
        events.extend(parse_boj_events(year))
    except Exception:
        pass
    try:
        events.extend(parse_bls_events())
    except Exception:
        pass
    events.extend(load_custom_events())
    unique = {(item.event_date, item.title): item for item in events}
    return sorted(unique.values(), key=lambda item: item.event_date)


def build_event_risk_at(events: list[EventItem], now: datetime) -> EventRisk:
    today = now.date()
    future = [event for event in events if event.event_date >= today - timedelta(days=1)]
    next_events = [event for event in future if event.event_date >= today][:5]
    items: list[str] = []
    warnings: list[str] = []
    level = "low"
    title = "通常"
    score_cap: int | None = None

    for event in future:
        delta = (event.event_date - today).days
        if -1 <= delta <= 1:
            level = "high"
            title = "重要イベント前後"
            score_cap = 60
            items.append(f"{event.event_date:%m/%d}: {event.title}")
        elif 2 <= delta <= 5 and level != "high":
            level = "medium"
            title = "重要イベント接近"
            score_cap = 72
            items.append(f"{event.event_date:%m/%d}: {event.title}")

    if now.weekday() < 5 and (
        now.hour == 21
        or now.hour == 22
        or (now.hour == 23 and now.minute <= 15)
        or (now.hour == 0 and now.minute <= 15)
    ):
        level = "high"
        title = "米指標時間帯"
        score_cap = 60
        items.append("21:00-00:15 JSTは米指標発表が多く、急変しやすい時間帯")

    if level == "high":
        warnings.append("重要イベント前後は、テクニカルの候補価格が機能しにくい場合があります")
    elif level == "medium":
        warnings.append("数日内に重要イベントがあり、ポジション持ち越しは注意")

    return EventRisk(
        level=level,
        title=title,
        score_cap=score_cap,
        items=items,
        next_events=next_events,
        warnings=warnings,
    )


def build_event_risk(events: list[EventItem]) -> EventRisk:
    return build_event_risk_at(events, datetime.now(JST))


def build_setup(
    pair: str,
    hourly: pd.DataFrame,
    h4: pd.DataFrame,
    daily: pd.DataFrame,
    regime: MarketRegime,
    macro: MacroContext,
    event_risk: EventRisk,
) -> Setup:
    latest_h1 = hourly.iloc[-1]
    prev_h1 = hourly.iloc[-2]
    latest_h4 = h4.iloc[-1]
    latest_d = daily.iloc[-1]
    prev_d = daily.iloc[-6] if len(daily) >= 6 else daily.iloc[-2]

    current = float(latest_h1["Close"])
    atr = float(latest_h4["ATR14"])
    if not np.isfinite(atr) or atr <= 0:
        atr = float((h4["High"] - h4["Low"]).tail(20).mean())

    recent = h4.tail(36)
    support = float(recent["Low"].min())
    resistance = float(recent["High"].max())

    daily_bull = (
        latest_d["Close"] > latest_d["EMA20"] > latest_d["SMA50"]
        and latest_d["EMA20"] > prev_d["EMA20"]
    )
    daily_bear = (
        latest_d["Close"] < latest_d["EMA20"] < latest_d["SMA50"]
        and latest_d["EMA20"] < prev_d["EMA20"]
    )
    h4_bull = latest_h4["Close"] > latest_h4["EMA20"] and latest_h4["MACD"] >= latest_h4["MACD_SIGNAL"]
    h4_bear = latest_h4["Close"] < latest_h4["EMA20"] and latest_h4["MACD"] <= latest_h4["MACD_SIGNAL"]
    h1_rsi_up = latest_h1["RSI14"] > prev_h1["RSI14"]
    h1_rsi_down = latest_h1["RSI14"] < prev_h1["RSI14"]
    near_support = pct_distance(current, support) <= max(0.004, (atr / current) * 1.2)
    near_resistance = pct_distance(current, resistance) <= max(0.004, (atr / current) * 1.2)
    near_bb_lower = latest_h4["Close"] <= latest_h4["BB_LOWER"] + atr * 0.35
    near_bb_upper = latest_h4["Close"] >= latest_h4["BB_UPPER"] - atr * 0.35

    buy_score = 0
    sell_score = 0
    buy_reasons: list[str] = []
    sell_reasons: list[str] = []
    warnings: list[str] = []

    if daily_bull:
        buy_score += 30
        buy_reasons.append("日足は上昇トレンド")
    elif daily_bear:
        sell_score += 30
        sell_reasons.append("日足は下降トレンド")
    else:
        buy_score += 8
        sell_score += 8

    if h4_bull:
        buy_score += 22
        buy_reasons.append("4時間足は20EMAより上で推移")
    if h4_bear:
        sell_score += 22
        sell_reasons.append("4時間足は20EMAより下で推移")

    if 34 <= latest_h1["RSI14"] <= 58 and h1_rsi_up:
        buy_score += 16
        buy_reasons.append("1時間足RSIが押し目圏から上向き")
    if 42 <= latest_h1["RSI14"] <= 66 and h1_rsi_down:
        sell_score += 16
        sell_reasons.append("1時間足RSIが戻り圏から下向き")

    if near_support:
        buy_score += 12
        buy_reasons.append("現在値が直近サポートに近い")
    if near_resistance:
        sell_score += 12
        sell_reasons.append("現在値が直近レジスタンスに近い")

    if regime.name == "レンジ/収縮":
        if near_bb_lower:
            buy_score += 10
            buy_reasons.append("レンジ気味で4時間足がボリンジャー下限付近")
        if near_bb_upper:
            sell_score += 10
            sell_reasons.append("レンジ気味で4時間足がボリンジャー上限付近")

    if latest_h1["MACD"] > latest_h1["MACD_SIGNAL"]:
        buy_score += 7
        buy_reasons.append("1時間足MACDが上向き")
    if latest_h1["MACD"] < latest_h1["MACD_SIGNAL"]:
        sell_score += 7
        sell_reasons.append("1時間足MACDが下向き")

    if regime.bias == "buy":
        buy_score += regime.score
        buy_reasons.extend(regime.reasons)
    elif regime.bias == "sell":
        sell_score += regime.score
        sell_reasons.extend(regime.reasons)
    elif regime.score < 0:
        buy_score += regime.score
        sell_score += regime.score
    warnings.extend(regime.warnings)

    if macro.bias == "buy":
        buy_score += macro.score
        buy_reasons.extend(macro.reasons)
    elif macro.bias == "sell":
        sell_score += macro.score
        sell_reasons.extend(macro.reasons)
    else:
        buy_reasons.extend(macro.reasons[:1])
        sell_reasons.extend(macro.reasons[:1])
    warnings.extend(macro.warnings)
    warnings.extend(event_risk.warnings)

    if latest_h1["RSI14"] >= 70:
        warnings.append("RSIが高く、買いは追いかけ注意")
    if latest_h1["RSI14"] <= 30:
        warnings.append("RSIが低く、売りは追いかけ注意")
    if resistance - support < atr * 1.4:
        warnings.append("値幅が狭く、利確余地が小さい可能性")

    if buy_score >= sell_score + 8 and buy_score >= 48:
        direction = "買い優勢"
        bias = "buy"
        score = min(90, buy_score)
        center = max(support, current - atr * 0.25)
        entry_low = center - atr * 0.20
        entry_high = center + atr * 0.35
        stop = min(support - atr * 0.65, entry_low - atr * 0.70)
        mid = (entry_low + entry_high) / 2
        risk = max(mid - stop, atr * 0.8)
        target_1 = mid + risk * 1.5
        target_2 = mid + risk * 2.2
        reasons = buy_reasons
    elif sell_score >= buy_score + 8 and sell_score >= 48:
        direction = "売り優勢"
        bias = "sell"
        score = min(90, sell_score)
        center = min(resistance, current + atr * 0.25)
        entry_low = center - atr * 0.35
        entry_high = center + atr * 0.20
        stop = max(resistance + atr * 0.65, entry_high + atr * 0.70)
        mid = (entry_low + entry_high) / 2
        risk = max(stop - mid, atr * 0.8)
        target_1 = mid - risk * 1.5
        target_2 = mid - risk * 2.2
        reasons = sell_reasons
    else:
        direction = "様子見"
        bias = "wait"
        score = max(buy_score, sell_score)
        entry_low = support
        entry_high = resistance
        stop = np.nan
        target_1 = np.nan
        target_2 = np.nan
        reasons = ["方向感が揃いきっていない", "サポート・レジスタンス到達待ち"]
        if regime.reasons:
            reasons.extend(regime.reasons[:1])

    if event_risk.score_cap is not None:
        score = min(int(score), event_risk.score_cap)
    score = max(0, int(score))

    return Setup(
        direction=direction,
        bias=bias,
        score=score,
        entry_low=float(entry_low),
        entry_high=float(entry_high),
        stop=float(stop),
        target_1=float(target_1),
        target_2=float(target_2),
        support=support,
        resistance=resistance,
        atr=atr,
        reasons=list(dict.fromkeys(reasons)),
        warnings=list(dict.fromkeys(warnings)),
    )


def chart_figure(data: pd.DataFrame, pair: str, setup: Setup) -> go.Figure:
    shown = data.tail(160)
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=shown.index,
            open=shown["Open"],
            high=shown["High"],
            low=shown["Low"],
            close=shown["Close"],
            name="Price",
            increasing_line_color="#107a53",
            decreasing_line_color="#b42318",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=shown.index,
            y=shown["EMA20"],
            mode="lines",
            line=dict(color="#1f77b4", width=1.4),
            name="EMA20",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=shown.index,
            y=shown["SMA50"],
            mode="lines",
            line=dict(color="#9467bd", width=1.2),
            name="SMA50",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=shown.index,
            y=shown["BB_UPPER"],
            mode="lines",
            line=dict(color="#8a96a3", width=1, dash="dot"),
            name="BB Upper",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=shown.index,
            y=shown["BB_LOWER"],
            mode="lines",
            line=dict(color="#8a96a3", width=1, dash="dot"),
            name="BB Lower",
        )
    )
    fig.add_hline(y=setup.support, line_color="#107a53", line_width=1, line_dash="dot")
    fig.add_hline(y=setup.resistance, line_color="#b42318", line_width=1, line_dash="dot")
    if setup.bias in {"buy", "sell"}:
        fig.add_hrect(
            y0=setup.entry_low,
            y1=setup.entry_high,
            fillcolor="#f0b429",
            opacity=0.18,
            line_width=0,
        )
    fig.update_layout(
        height=520,
        margin=dict(l=10, r=10, t=24, b=10),
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(title=pair),
    )
    return fig


def signal_class(bias: str) -> str:
    return {"buy": "ok", "sell": "bad", "wait": "wait"}.get(bias, "wait")


def box(title: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="signal-box">
          <div class="signal-title">{title}</div>
          <div class="signal-value">{value}</div>
          <div class="muted">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def default_notification_config() -> dict[str, object]:
    return {
        "enabled": True,
        "topic": f"usdjpy-signal-{secrets.token_hex(8)}",
        "score_threshold": 68,
        "interval_minutes": 15,
        "cooldown_minutes": 180,
        "notify_during_high_event": False,
    }


def load_notification_config() -> dict[str, object]:
    if not NOTIFICATION_CONFIG_PATH.exists():
        config = default_notification_config()
        save_notification_config(config)
        return config
    try:
        loaded = json.loads(NOTIFICATION_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        loaded = {}
    config = default_notification_config()
    config.update({k: v for k, v in loaded.items() if v is not None})
    if not str(config.get("topic", "")).strip():
        config["topic"] = default_notification_config()["topic"]
    return config


def save_notification_config(config: dict[str, object]) -> None:
    NOTIFICATION_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_notification_state() -> dict[str, object]:
    if not NOTIFICATION_STATE_PATH.exists():
        return {}
    try:
        return json.loads(NOTIFICATION_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_notification_state(state: dict[str, object]) -> None:
    NOTIFICATION_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def notification_topic_url(topic: str) -> str:
    return f"{NTFY_SERVER}/{topic.strip()}"


def notification_subscribe_url(topic: str) -> str:
    return f"ntfy://ntfy.sh/{topic.strip()}?display=USDJPY"


def ntfy_header_text(value: str, fallback: str) -> str:
    safe = value.encode("latin-1", errors="ignore").decode("latin-1").strip()
    return safe or fallback


def send_ntfy_notification(
    topic: str,
    title: str,
    message: str,
    priority: str = "default",
    click_url: str = DEFAULT_DASHBOARD_URL,
) -> None:
    safe_topic = topic.strip()
    if not safe_topic:
        raise ValueError("通知トピックが未設定です。")
    headers = {
        "Title": ntfy_header_text(title, "USDJPY Signal"),
        "Priority": priority,
        "Tags": "chart_with_upwards_trend",
    }
    if click_url:
        headers["Click"] = click_url
    response = requests.post(
        notification_topic_url(safe_topic),
        data=message.encode("utf-8"),
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()


def is_entry_chance(setup: Setup, event_risk: EventRisk, config: dict[str, object]) -> tuple[bool, str]:
    threshold = int(config.get("score_threshold", 68))
    allow_high_event = bool(config.get("notify_during_high_event", False))
    if setup.bias not in {"buy", "sell"}:
        return False, "買い/売り優勢ではない"
    if setup.score < threshold:
        return False, f"信頼度がしきい値未満 ({setup.score}% < {threshold}%)"
    if event_risk.level == "high" and not allow_high_event:
        return False, "重要イベント前後のため通知抑制"
    return True, "通知対象"


def signal_key(setup: Setup) -> str:
    return setup.bias


def build_notification_message(result: AnalysisResult) -> tuple[str, str]:
    setup = result.setup
    side = "BUY" if setup.bias == "buy" else "SELL"
    title = f"USDJPY {side} {setup.score}%"
    stop = "未設定" if setup.bias == "wait" else fmt_price(setup.stop, PAIR)
    target = "未設定" if setup.bias == "wait" else f"{fmt_price(setup.target_1, PAIR)} / {fmt_price(setup.target_2, PAIR)}"
    reasons = " / ".join(setup.reasons[:3])
    message = (
        f"{setup.direction}\n"
        f"現在価格: {fmt_price(result.current_price, PAIR)}\n"
        f"候補ゾーン: {fmt_price(setup.entry_low, PAIR)} - {fmt_price(setup.entry_high, PAIR)}\n"
        f"損切り: {stop}\n"
        f"利確: {target}\n"
        f"相場環境: {result.regime.name}\n"
        f"米金利: {result.macro.name}\n"
        f"根拠: {reasons}"
    )
    return title, message


def comparable_timestamp(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        return ts.tz_convert("UTC").tz_localize(None)
    return ts


def slice_until(data: pd.DataFrame, current_time: object) -> pd.DataFrame:
    if data.empty:
        return data
    target = comparable_timestamp(current_time)
    index = pd.DatetimeIndex(data.index)
    if index.tz is not None:
        comparable_index = index.tz_convert("UTC").tz_localize(None)
    else:
        comparable_index = index
    return data.loc[comparable_index <= target]


def datetime_for_event_check(value: object) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.to_pydatetime().replace(tzinfo=JST)
    return ts.tz_convert(JST).to_pydatetime()


def yields_until(yields: pd.DataFrame, current_day: date) -> pd.DataFrame:
    if yields.empty or "date" not in yields.columns:
        return pd.DataFrame(columns=["date", "2Y", "10Y"])
    return yields[yields["date"] <= current_day].copy()


def evaluate_trade_exit(
    future: pd.DataFrame,
    side: str,
    entry: float,
    stop: float,
    target: float,
    max_hold_bars: int,
) -> tuple[object, float, str]:
    hold = future.head(max_hold_bars)
    if hold.empty:
        return None, entry, "no_data"

    for bar_time, bar in hold.iterrows():
        high = float(bar["High"])
        low = float(bar["Low"])
        if side == "buy":
            stop_hit = low <= stop
            target_hit = high >= target
            if stop_hit and target_hit:
                return bar_time, stop, "loss"
            if target_hit:
                return bar_time, target, "win"
            if stop_hit:
                return bar_time, stop, "loss"
        else:
            stop_hit = high >= stop
            target_hit = low <= target
            if stop_hit and target_hit:
                return bar_time, stop, "loss"
            if target_hit:
                return bar_time, target, "win"
            if stop_hit:
                return bar_time, stop, "loss"

    last_time = hold.index[-1]
    last_close = float(hold.iloc[-1]["Close"])
    return last_time, last_close, "timeout"


def find_entry(
    future: pd.DataFrame,
    setup: Setup,
    mode: str,
    expire_bars: int,
) -> tuple[object, float, pd.DataFrame] | None:
    if future.empty:
        return None
    if mode == "next_open":
        entry_time = future.index[0]
        entry_price = float(future.iloc[0]["Open"])
        return entry_time, entry_price, future

    entry_price = (setup.entry_low + setup.entry_high) / 2
    search = future.head(expire_bars)
    for entry_time, bar in search.iterrows():
        if float(bar["Low"]) <= entry_price <= float(bar["High"]):
            return entry_time, float(entry_price), future.loc[entry_time:]
    return None


def summarize_backtest(trades: list[BacktestTrade], checked: int, skipped: int) -> BacktestResult:
    if not trades:
        return BacktestResult(
            trades=[],
            skipped_signals=skipped,
            checked_signals=checked,
            win_rate=0.0,
            total_r=0.0,
            average_r=0.0,
            profit_factor=0.0,
            max_drawdown_r=0.0,
            max_losing_streak=0,
            suggested_threshold=None,
        )

    r_values = [trade.r_multiple for trade in trades]
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value < 0]
    equity = np.cumsum(r_values)
    peak = np.maximum.accumulate(equity)
    drawdown = equity - peak
    losing_streak = 0
    max_losing_streak = 0
    for value in r_values:
        if value < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0

    suggested_threshold = None
    best_score = -999.0
    for threshold in [60, 65, 68, 70, 72, 75, 78, 80]:
        filtered = [trade.r_multiple for trade in trades if trade.score >= threshold]
        if len(filtered) < 5:
            continue
        score = float(np.mean(filtered)) * min(len(filtered), 25)
        if score > best_score:
            best_score = score
            suggested_threshold = threshold

    return BacktestResult(
        trades=trades,
        skipped_signals=skipped,
        checked_signals=checked,
        win_rate=len(wins) / len(trades) * 100,
        total_r=float(np.sum(r_values)),
        average_r=float(np.mean(r_values)),
        profit_factor=float(np.sum(wins) / abs(np.sum(losses))) if losses else float("inf"),
        max_drawdown_r=abs(float(drawdown.min())) if len(drawdown) else 0.0,
        max_losing_streak=max_losing_streak,
        suggested_threshold=suggested_threshold,
    )


@st.cache_data(ttl=15 * 60, show_spinner=False)
def run_backtest(
    period: str,
    threshold: int,
    entry_mode: str,
    expire_bars: int,
    max_hold_bars: int,
    target_choice: str,
    step_bars: int,
) -> BacktestResult:
    hourly_raw, daily_raw = fetch_backtest_prices(TICKER, period)
    if hourly_raw.empty or daily_raw.empty:
        return summarize_backtest([], 0, 0)

    hourly = with_indicators(hourly_raw)
    daily = with_indicators(daily_raw)
    try:
        treasury = fetch_treasury_yields()
    except Exception:
        treasury = pd.DataFrame(columns=["date", "2Y", "10Y"])
    events = fetch_policy_events()

    config = {
        "score_threshold": threshold,
        "notify_during_high_event": False,
    }
    trades: list[BacktestTrade] = []
    checked = 0
    skipped = 0
    next_allowed_position = 0

    for position in range(80, len(hourly) - max_hold_bars - 1, max(1, step_bars)):
        if position < next_allowed_position:
            continue
        current_time = hourly.index[position]
        hourly_slice = hourly.iloc[: position + 1]
        h4_slice = with_indicators(to_4h(hourly_raw.loc[:current_time]))
        daily_slice = slice_until(daily, current_time)
        if len(hourly_slice) < 80 or len(h4_slice) < 40 or len(daily_slice) < 80:
            continue

        current_dt = datetime_for_event_check(current_time)
        regime = analyze_regime(h4_slice)
        macro = build_macro_context(yields_until(treasury, current_dt.date()), current_dt.date())
        event_risk = build_event_risk_at(events, current_dt)
        setup = build_setup(PAIR, hourly_slice, h4_slice, daily_slice, regime, macro, event_risk)
        checked += 1
        ok, _ = is_entry_chance(setup, event_risk, config)
        if not ok:
            continue

        target = setup.target_2 if target_choice == "target_2" else setup.target_1
        if not all(np.isfinite(value) for value in [setup.stop, target, setup.entry_low, setup.entry_high]):
            skipped += 1
            continue

        future = hourly.iloc[position + 1 :]
        entry = find_entry(future, setup, entry_mode, expire_bars)
        if entry is None:
            skipped += 1
            continue
        entry_time, entry_price, future_after_entry = entry
        risk = abs(entry_price - setup.stop)
        if risk <= 0:
            skipped += 1
            continue

        exit_time, exit_price, result = evaluate_trade_exit(
            future_after_entry,
            setup.bias,
            entry_price,
            setup.stop,
            target,
            max_hold_bars,
        )
        if exit_time is None:
            skipped += 1
            continue

        raw_profit = exit_price - entry_price if setup.bias == "buy" else entry_price - exit_price
        pips = raw_profit * 100
        r_multiple = raw_profit / risk
        trades.append(
            BacktestTrade(
                signal_time=current_time,
                entry_time=entry_time,
                exit_time=exit_time,
                side=setup.bias,
                score=setup.score,
                entry=float(entry_price),
                stop=float(setup.stop),
                target=float(target),
                exit_price=float(exit_price),
                result=result,
                pips=float(pips),
                r_multiple=float(r_multiple),
            )
        )
        next_allowed_position = min(len(hourly), position + max_hold_bars)

    return summarize_backtest(trades, checked, skipped)


def backtest_trades_frame(trades: list[BacktestTrade]) -> pd.DataFrame:
    rows = []
    for trade in trades:
        rows.append(
            {
                "signal_time": trade.signal_time,
                "entry_time": trade.entry_time,
                "exit_time": trade.exit_time,
                "side": "買い" if trade.side == "buy" else "売り",
                "score": trade.score,
                "entry": round(trade.entry, 3),
                "stop": round(trade.stop, 3),
                "target": round(trade.target, 3),
                "exit": round(trade.exit_price, 3),
                "result": trade.result,
                "pips": round(trade.pips, 1),
                "R": round(trade.r_multiple, 2),
            }
        )
    return pd.DataFrame(rows)


def backtest_equity_figure(trades: list[BacktestTrade]) -> go.Figure:
    if not trades:
        return go.Figure()
    frame = backtest_trades_frame(trades)
    frame["equity_r"] = frame["R"].cumsum()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["exit_time"],
            y=frame["equity_r"],
            mode="lines+markers",
            name="Cumulative R",
            line=dict(color="#1f77b4", width=2),
        )
    )
    fig.update_layout(
        height=360,
        margin=dict(l=10, r=10, t=24, b=10),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        yaxis=dict(title="Cumulative R"),
    )
    return fig


def render_backtest_section(default_threshold: int) -> None:
    st.subheader("バックテスト")
    st.caption("過去データの各時点で判定を作り直し、候補ゾーン到達後の利確/損切りを検証します。未来の価格は判定に使いません。")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        period = st.selectbox("検証期間", ["90d", "180d", "365d", "730d"], index=0)
    with c2:
        threshold = st.slider("検証する信頼度", 50, 90, int(default_threshold), 1)
    with c3:
        target_choice_label = st.selectbox("利確", ["第1利確", "第2利確"], index=0)
    with c4:
        entry_mode_label = st.selectbox("エントリー", ["候補ゾーン到達", "次の足の始値"], index=0)

    c5, c6, c7 = st.columns(3)
    with c5:
        expire_bars = st.number_input("候補ゾーン待ち時間", min_value=1, max_value=48, value=12, step=1)
    with c6:
        max_hold_bars = st.number_input("最大保有時間", min_value=4, max_value=120, value=48, step=4)
    with c7:
        step_bars = st.number_input("判定間隔", min_value=1, max_value=12, value=4, step=1)

    entry_mode = "next_open" if entry_mode_label == "次の足の始値" else "candidate_zone"
    target_choice = "target_2" if target_choice_label == "第2利確" else "target_1"
    with st.spinner("バックテスト中..."):
        result = run_backtest(period, threshold, entry_mode, int(expire_bars), int(max_hold_bars), target_choice, int(step_bars))

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("取引数", len(result.trades))
    m2.metric("勝率", f"{result.win_rate:.1f}%")
    m3.metric("合計R", f"{result.total_r:.2f}")
    m4.metric("平均R", f"{result.average_r:.2f}")
    m5.metric("最大DD", f"{result.max_drawdown_r:.2f}R")

    m6, m7, m8 = st.columns(3)
    pf_text = "∞" if np.isinf(result.profit_factor) else f"{result.profit_factor:.2f}"
    m6.metric("PF", pf_text)
    m7.metric("最大連敗", result.max_losing_streak)
    m8.metric("未約定/除外", result.skipped_signals)
    st.caption(f"判定した過去シグナル数: {result.checked_signals}")

    if result.suggested_threshold is not None:
        st.info(f"この期間だけで見ると、信頼度 {result.suggested_threshold}% 以上が比較的よさそうです。ただし過去に合わせすぎる危険があるので、すぐ自動変更せず目安として見てください。")
    elif len(result.trades) < 5:
        st.warning("取引数が少ないため、勝率や推奨しきい値はまだ判断材料として弱いです。")

    st.plotly_chart(backtest_equity_figure(result.trades), use_container_width=True)
    frame = backtest_trades_frame(result.trades)
    if not frame.empty:
        st.dataframe(frame.sort_values("entry_time", ascending=False), use_container_width=True, hide_index=True)


def analyze_market() -> AnalysisResult:
    hourly_raw, daily_raw = fetch_prices(TICKER)
    if hourly_raw.empty or daily_raw.empty:
        raise RuntimeError("価格データが取得できませんでした。")

    hourly = with_indicators(hourly_raw)
    h4 = with_indicators(to_4h(hourly_raw))
    daily = with_indicators(daily_raw)
    if len(hourly) < 80 or len(h4) < 40 or len(daily) < 80:
        raise RuntimeError("分析に必要な本数が足りません。")

    treasury_warning = ""
    try:
        treasury = fetch_treasury_yields()
    except Exception as exc:
        treasury = pd.DataFrame(columns=["date", "2Y", "10Y"])
        treasury_warning = f"米金利データを取得できなかったため、金利フィルターは中立扱いです: {exc}"
    events = fetch_policy_events()
    regime = analyze_regime(h4)
    macro = build_macro_context(treasury)
    if treasury_warning:
        macro.warnings.append(treasury_warning)
    event_risk = build_event_risk(events)
    setup = build_setup(PAIR, hourly, h4, daily, regime, macro, event_risk)
    current_price = float(hourly.iloc[-1]["Close"])
    latest_time = hourly.index[-1]
    return AnalysisResult(
        hourly=hourly,
        h4=h4,
        daily=daily,
        treasury=treasury,
        events=events,
        regime=regime,
        macro=macro,
        event_risk=event_risk,
        setup=setup,
        current_price=current_price,
        latest_time=latest_time,
    )


def ensure_custom_events_file() -> None:
    if CUSTOM_EVENTS_PATH.exists():
        return
    CUSTOM_EVENTS_PATH.write_text(
        "date,title,impact\n"
        "# 例: 2026-06-05,米雇用統計,high\n"
        "# 公式予定を手で追加したい時だけ、先頭の # を外して使います。\n",
        encoding="utf-8",
    )


def main() -> None:
    ensure_custom_events_file()
    notification_config = load_notification_config()

    with st.sidebar:
        st.title("USD/JPY Signal Desk")
        st.metric("対象通貨ペア", PAIR)
        refresh = st.button("データ更新", use_container_width=True)
        st.caption("無料データを使うため、価格・米金利・イベント情報は遅延や欠損があり得ます。")
        st.divider()
        st.caption("売買判断の補助ツールです。利益を保証するものではありません。実運用前に必ずデモ検証してください。")
        st.divider()
        with st.expander("スマホ通知", expanded=False):
            notification_config["enabled"] = st.checkbox(
                "通知を有効にする",
                value=bool(notification_config.get("enabled", True)),
            )
            notification_config["topic"] = st.text_input(
                "ntfyトピック",
                value=str(notification_config.get("topic", "")),
                help="推測されにくい文字列にしてください。知っている人は同じ通知を受け取れます。",
            ).strip()
            notification_config["score_threshold"] = st.slider(
                "通知する信頼度",
                min_value=50,
                max_value=90,
                value=int(notification_config.get("score_threshold", 68)),
                step=1,
            )
            notification_config["interval_minutes"] = st.number_input(
                "監視間隔（分）",
                min_value=5,
                max_value=120,
                value=int(notification_config.get("interval_minutes", 15)),
                step=5,
            )
            notification_config["cooldown_minutes"] = st.number_input(
                "同じ通知の再通知間隔（分）",
                min_value=30,
                max_value=720,
                value=int(notification_config.get("cooldown_minutes", 180)),
                step=30,
            )
            notification_config["notify_during_high_event"] = st.checkbox(
                "重要イベント前後も通知する",
                value=bool(notification_config.get("notify_during_high_event", False)),
            )
            save_notification_config(notification_config)
            topic = str(notification_config["topic"])
            st.markdown(f"[スマホ購読リンク]({notification_subscribe_url(topic)})")
            st.caption("スマホにntfyアプリを入れて、このトピックを購読します。")
            if st.button("テスト通知を送る", use_container_width=True):
                try:
                    send_ntfy_notification(topic, "USDJPY Test", "FX Signal Deskからのテスト通知です。")
                    st.success("テスト通知を送りました。")
                except Exception as exc:
                    st.error(f"通知送信に失敗しました: {exc}")

    if refresh:
        fetch_prices.clear()
        fetch_treasury_yields.clear()
        fetch_policy_events.clear()

    try:
        with st.spinner("データを取得しています..."):
            result = analyze_market()
    except Exception as exc:
        st.error(f"データ取得に失敗しました: {exc}")
        st.stop()

    hourly = result.hourly
    daily = result.daily
    regime = result.regime
    macro = result.macro
    event_risk = result.event_risk
    setup = result.setup
    current_price = result.current_price
    latest_time = result.latest_time
    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    st.title("USD/JPY Signal Desk")
    st.caption(f"{PAIR} / 最終価格データ: {latest_time} / 表示更新: {now_jst} JST")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("現在価格", fmt_price(current_price, PAIR))
    c2.metric("判定", setup.direction)
    c3.metric("信頼度目安", f"{setup.score}%")
    c4.metric("相場環境", regime.name)
    c5.metric("米10年債", f"{macro.ten_year:.2f}%" if macro.ten_year is not None else "-")

    st.plotly_chart(chart_figure(hourly, PAIR, setup), use_container_width=True)

    left, middle, right = st.columns([1, 1, 1])
    with left:
        box(
            "候補ゾーン",
            f"{fmt_price(setup.entry_low, PAIR)} - {fmt_price(setup.entry_high, PAIR)}",
            "黄色の帯で表示",
        )
    with middle:
        stop_text = "未設定" if setup.bias == "wait" else fmt_price(setup.stop, PAIR)
        box("損切り候補", stop_text, "ATRと直近高値/安値から算出")
    with right:
        target_text = "未設定" if setup.bias == "wait" else f"{fmt_price(setup.target_1, PAIR)} / {fmt_price(setup.target_2, PAIR)}"
        box("利確候補", target_text, "リスクリワードから算出")

    st.subheader("追加フィルター")
    f1, f2, f3 = st.columns(3)
    with f1:
        box(
            "相場環境",
            regime.name,
            f"ADX {regime.adx:.1f} / BB幅順位 {regime.bb_rank:.0f}% / EMA傾き {regime.ema_slope:+.2f}%",
        )
    with f2:
        yield_note = (
            f"5営業日 {fmt_signed(macro.ten_year_5d, '%pt')} / 20営業日 {fmt_signed(macro.ten_year_20d, '%pt')}"
            if macro.ten_year is not None
            else "米財務省データ未取得"
        )
        box("米金利", macro.name, yield_note)
    with f3:
        event_note = " / ".join(event_risk.items[:2]) if event_risk.items else "近い重要イベントは検出なし"
        box("イベント注意", event_risk.title, event_note)

    info_left, info_right = st.columns([1, 1])
    with info_left:
        st.subheader("根拠")
        for reason in setup.reasons[:9]:
            st.markdown(f"- {reason}")
        st.markdown(
            f'<p class="{signal_class(setup.bias)}">現在の見立て: {setup.direction}</p>',
            unsafe_allow_html=True,
        )
        if setup.warnings:
            st.subheader("注意")
            for warning in setup.warnings:
                st.markdown(f"- {warning}")

    with info_right:
        st.subheader("水準")
        st.markdown(f"- 直近サポート: {fmt_price(setup.support, PAIR)}")
        st.markdown(f"- 直近レジスタンス: {fmt_price(setup.resistance, PAIR)}")
        st.markdown(f"- 日足RSI: {daily.iloc[-1]['RSI14']:.1f}")
        st.markdown(f"- 1時間足RSI: {hourly.iloc[-1]['RSI14']:.1f}")
        st.markdown(f"- 4時間足ADX: {regime.adx:.1f}")
        st.markdown(f"- 4時間足BB幅: {regime.bb_width:.2f}%")
        if macro.last_date is not None:
            st.markdown(f"- 米金利最終日: {macro.last_date:%Y-%m-%d}")
        if event_risk.next_events:
            st.subheader("次の重要イベント")
            for event in event_risk.next_events[:4]:
                st.markdown(f"- {event.event_date:%Y-%m-%d}: {event.title}")

    st.divider()
    render_backtest_section(int(notification_config.get("score_threshold", 68)))


if __name__ == "__main__":
    main()

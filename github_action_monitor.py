from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests

import app


def default_dashboard_url() -> str:
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    if "/" in repository:
        owner, repo = repository.split("/", 1)
        return f"https://{owner}.github.io/{repo}/"
    return "https://taitotoni0606.github.io/fx-signal-tool/"


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/") + "/" if url.strip() else default_dashboard_url()


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def github_config() -> dict[str, object]:
    return {
        "enabled": env_bool("NOTIFY_ENABLED", True),
        "topic": os.getenv("NTFY_TOPIC", "").strip(),
        "score_threshold": int(os.getenv("SCORE_THRESHOLD", "68")),
        "cooldown_minutes": int(os.getenv("COOLDOWN_MINUTES", "180")),
        "notify_during_high_event": env_bool("NOTIFY_DURING_HIGH_EVENT", False),
        "dashboard_url": normalize_url(os.getenv("DASHBOARD_URL", default_dashboard_url())),
    }


def read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def published_state_url(dashboard_url: str) -> str:
    return normalize_url(dashboard_url) + "notification_state.json"


def read_published_state(dashboard_url: str) -> dict[str, object]:
    try:
        response = requests.get(
            published_state_url(dashboard_url),
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.ok:
            data = response.json()
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def load_state(state_path: Path, dashboard_url: str) -> dict[str, object]:
    local_state = read_json(state_path)
    if local_state:
        return local_state
    return read_published_state(dashboard_url)


def write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def h(text: object) -> str:
    return html.escape(str(text), quote=True)


def metric(label: str, value: str, note: str = "") -> str:
    note_html = f"<span>{h(note)}</span>" if note else ""
    return f"""
    <section class="metric">
      <p>{h(label)}</p>
      <strong>{h(value)}</strong>
      {note_html}
    </section>
    """


def sparkline(values: list[float]) -> str:
    if len(values) < 2:
        return ""
    width = 680
    height = 190
    lo = min(values)
    hi = max(values)
    span = hi - lo if hi != lo else 1
    points = []
    for idx, value in enumerate(values):
        x = idx / (len(values) - 1) * width
        y = height - ((value - lo) / span * (height - 18)) - 9
        points.append(f"{x:.1f},{y:.1f}")
    color = "#107a53" if values[-1] >= values[0] else "#b42318"
    return f"""
    <svg class="spark" viewBox="0 0 {width} {height}" role="img" aria-label="USD/JPY price line">
      <polyline fill="none" stroke="{color}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" points="{' '.join(points)}"/>
    </svg>
    """


def setup_values(result: app.AnalysisResult) -> tuple[str, str, str]:
    setup = result.setup
    entry = f"{app.fmt_price(setup.entry_low, app.PAIR)} - {app.fmt_price(setup.entry_high, app.PAIR)}"
    stop = "未設定" if setup.bias == "wait" else app.fmt_price(setup.stop, app.PAIR)
    target = "未設定" if setup.bias == "wait" else f"{app.fmt_price(setup.target_1, app.PAIR)} / {app.fmt_price(setup.target_2, app.PAIR)}"
    return entry, stop, target


def generate_dashboard(result: app.AnalysisResult, state: dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    setup = result.setup
    entry, stop, target = setup_values(result)
    now_jst = datetime.now(app.JST).strftime("%Y-%m-%d %H:%M")
    closes = [float(v) for v in result.hourly["Close"].tail(90).tolist()]
    direction_class = {"buy": "buy", "sell": "sell", "wait": "wait"}.get(setup.bias, "wait")
    reasons = "".join(f"<li>{h(reason)}</li>" for reason in setup.reasons[:8])
    warnings = "".join(f"<li>{h(warning)}</li>" for warning in setup.warnings[:6])
    next_events = "".join(
        f"<li>{event.event_date:%Y-%m-%d}: {h(event.title)}</li>"
        for event in result.event_risk.next_events[:5]
    )
    last_status = state.get("last_status", "未実行")

    content = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="300">
  <title>USD/JPY Signal Desk</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --text: #14181f;
      --muted: #667085;
      --line: #d8dee8;
      --buy: #107a53;
      --sell: #b42318;
      --wait: #835800;
      --accent: #1f77b4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    main {{
      width: min(960px, 100%);
      margin: 0 auto;
      padding: 18px 14px 36px;
    }}
    header {{
      display: grid;
      gap: 8px;
      margin-bottom: 14px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(1.8rem, 8vw, 3rem);
      letter-spacing: 0;
    }}
    .sub {{
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }}
    .hero, .card, .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .hero {{
      padding: 18px;
      margin-bottom: 12px;
    }}
    .status {{
      display: inline-flex;
      padding: 6px 10px;
      border-radius: 999px;
      font-weight: 700;
      margin-bottom: 10px;
    }}
    .status.buy {{ color: var(--buy); background: #e8f6ef; }}
    .status.sell {{ color: var(--sell); background: #fdecec; }}
    .status.wait {{ color: var(--wait); background: #fff5da; }}
    .price {{
      font-size: clamp(2.4rem, 14vw, 5rem);
      line-height: 1;
      font-weight: 800;
      letter-spacing: 0;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 10px 0;
    }}
    @media (min-width: 760px) {{
      .grid.four {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
      .grid.three {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    }}
    .metric {{
      padding: 12px;
      min-height: 98px;
    }}
    .metric p {{
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 0.84rem;
    }}
    .metric strong {{
      display: block;
      font-size: 1.15rem;
      line-height: 1.28;
      overflow-wrap: anywhere;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 0.8rem;
      margin-top: 6px;
      line-height: 1.35;
    }}
    .card {{
      padding: 14px;
      margin-top: 10px;
    }}
    h2 {{
      font-size: 1.05rem;
      margin: 0 0 10px;
    }}
    ul {{
      margin: 0;
      padding-left: 1.15rem;
      line-height: 1.6;
    }}
    .spark {{
      display: block;
      width: 100%;
      height: auto;
      margin-top: 14px;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>USD/JPY Signal Desk</h1>
      <div class="sub">更新: {h(now_jst)} JST / 最終価格データ: {h(result.latest_time)}</div>
    </header>

    <section class="hero">
      <div class="status {direction_class}">{h(setup.direction)} / 信頼度 {setup.score}%</div>
      <div class="price">{h(app.fmt_price(result.current_price, app.PAIR))}</div>
      {sparkline(closes)}
    </section>

    <div class="grid four">
      {metric("候補ゾーン", entry)}
      {metric("損切り候補", stop)}
      {metric("利確候補", target)}
      {metric("通知状態", str(last_status))}
    </div>

    <div class="grid three">
      {metric("相場環境", result.regime.name, f"ADX {result.regime.adx:.1f} / BB幅順位 {result.regime.bb_rank:.0f}%")}
      {metric("米金利", result.macro.name, f"10Y {result.macro.ten_year:.2f}%" if result.macro.ten_year is not None else "未取得")}
      {metric("イベント注意", result.event_risk.title, " / ".join(result.event_risk.items[:2]) if result.event_risk.items else "近い重要イベントなし")}
    </div>

    <section class="card">
      <h2>根拠</h2>
      <ul>{reasons}</ul>
    </section>

    <section class="card">
      <h2>注意</h2>
      <ul>{warnings or "<li>特になし</li>"}</ul>
    </section>

    <section class="card">
      <h2>次の重要イベント</h2>
      <ul>{next_events or "<li>検出なし</li>"}</ul>
    </section>
  </main>
</body>
</html>
"""
    output_path.write_text(content, encoding="utf-8")


def maybe_notify(result: app.AnalysisResult, state_path: Path) -> dict[str, object]:
    config = github_config()
    state = load_state(state_path, str(config.get("dashboard_url", "")))
    now = datetime.now(app.JST)

    ok, reason = app.is_entry_chance(result.setup, result.event_risk, config)
    state["last_checked_at"] = now.isoformat()

    if not config["enabled"]:
        state["last_status"] = "通知無効"
        write_json(state_path, state)
        return state

    if not ok:
        state["last_status"] = reason
        if result.setup.bias == "wait":
            state["last_signal_key"] = ""
        write_json(state_path, state)
        return state

    if not config["topic"]:
        state["last_status"] = "NTFY_TOPIC未設定"
        write_json(state_path, state)
        return state

    key = app.signal_key(result.setup)
    last_key = str(state.get("last_signal_key", ""))
    last_sent_at = parse_time(state.get("last_sent_at"))
    cooldown = timedelta(minutes=int(config.get("cooldown_minutes", 180)))
    same_side = key == last_key or last_key.startswith(f"{key}|")
    if same_side and last_sent_at and now - last_sent_at < cooldown:
        state["last_status"] = "cooldown"
        write_json(state_path, state)
        return state

    title, message = app.build_notification_message(result)
    priority = "high" if result.setup.score >= int(config.get("score_threshold", 68)) + 8 else "default"
    app.send_ntfy_notification(
        str(config["topic"]),
        title,
        message,
        priority=priority,
        click_url=str(config.get("dashboard_url", "")),
    )
    state.update(
        {
            "last_signal_key": key,
            "last_sent_at": now.isoformat(),
            "last_status": "sent",
            "last_title": title,
            "last_message": message,
        }
    )
    write_json(state_path, state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=".state/notification_state.json")
    parser.add_argument("--output", default="public/index.html")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()

    state_path = Path(args.state)
    output_path = Path(args.output)
    config = github_config()
    app.ensure_custom_events_file()
    result = app.analyze_market()
    if args.no_notify:
        state = load_state(state_path, str(config.get("dashboard_url", "")))
        state["last_checked_at"] = datetime.now(app.JST).isoformat()
        state["last_status"] = "dashboard only"
        write_json(state_path, state)
    else:
        state = maybe_notify(result, state_path)
    generate_dashboard(result, state, output_path)
    write_json(output_path.parent / "notification_state.json", state)
    print(json.dumps({"status": state.get("last_status"), "score": result.setup.score, "direction": result.setup.direction}, ensure_ascii=False))


if __name__ == "__main__":
    main()

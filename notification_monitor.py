from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

import app


LOG_PATH = Path(__file__).resolve().parent / "notification_monitor.log"


def log(message: str) -> None:
    stamp = datetime.now(app.JST).strftime("%Y-%m-%d %H:%M:%S")
    LOG_PATH.write_text(
        (LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else "")
        + f"[{stamp}] {message}\n",
        encoding="utf-8",
    )


def parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def send_test() -> None:
    config = app.load_notification_config()
    topic = str(config.get("topic", "")).strip()
    app.send_ntfy_notification(topic, "USDJPY Test", "通知設定は有効です。")
    log("test notification sent")


def run_check() -> None:
    config = app.load_notification_config()
    if not bool(config.get("enabled", True)):
        log("skip: notifications disabled")
        return

    try:
        app.fetch_prices.clear()
    except Exception:
        pass

    result = app.analyze_market()
    setup = result.setup
    state = app.load_notification_state()
    now = datetime.now(app.JST)

    state["last_checked_at"] = now.isoformat()
    topic = str(config.get("topic", "")).strip()
    if not topic:
        state["last_status"] = "ntfy topic missing"
        app.save_notification_state(state)
        log("skip: ntfy topic missing")
        return

    kind, reason = app.notification_kind(setup, result.event_risk, config)
    today = now.date().isoformat()

    def send(kind_name: str, priority: str = "default") -> None:
        title, message = app.build_notification_message(result, kind_name)
        app.send_ntfy_notification(topic, title, message, priority=priority)
        state.update(
            {
                "last_notification_date": today,
                "last_sent_at": now.isoformat(),
                "last_status": f"{kind_name} sent",
                "last_title": title,
                "last_message": message,
            }
        )
        state[f"last_{kind_name}_sent_at"] = now.isoformat()
        state[f"last_{kind_name}_title"] = title
        state[f"last_{kind_name}_message"] = message

    if kind == "main":
        key = app.signal_key(setup)
        last_key = str(state.get("last_main_signal_key", state.get("last_signal_key", "")))
        last_sent_at = parse_time(state.get("last_main_sent_at") or state.get("last_sent_at"))
        cooldown = timedelta(minutes=int(config.get("cooldown_minutes", 180)))
        same_side = key == last_key or last_key.startswith(f"{key}|")
        if same_side and last_sent_at and now - last_sent_at < cooldown:
            state["last_status"] = "main cooldown"
            app.save_notification_state(state)
            log(f"skip: main cooldown; signal={setup.direction}; score={setup.score}")
            return
        priority = "high" if setup.score >= int(config.get("score_threshold", 68)) + 8 else "default"
        send("main", priority)
        state["last_signal_key"] = key
        state["last_main_signal_key"] = key
        app.save_notification_state(state)
        log(f"sent main: {state.get('last_title')}")
        return

    if kind == "candidate":
        send("candidate", "default")
        state["last_candidate_signal_key"] = app.signal_key(setup)
        app.save_notification_state(state)
        log(f"sent candidate: {state.get('last_title')}")
        return

    daily_hour = int(config.get("daily_summary_hour", 8))
    sent_any_today = state.get("last_notification_date") == today
    already_sent_daily = state.get("last_daily_summary_date") == today
    if now.hour >= daily_hour and not sent_any_today and not already_sent_daily:
        send("daily", "low")
        state["last_daily_summary_date"] = today
        app.save_notification_state(state)
        log(f"sent daily: {state.get('last_title')}")
        return

    state["last_status"] = reason
    if setup.bias == "wait":
        state["last_signal_key"] = ""
    app.save_notification_state(state)
    log(f"skip: {reason}; signal={setup.direction}; score={setup.score}")
    return

def run_loop() -> None:
    while True:
        config = app.load_notification_config()
        interval_minutes = int(config.get("interval_minutes", 15))
        try:
            run_check()
        except Exception as exc:
            log(f"error: {exc}")
        time.sleep(max(5, interval_minutes * 60))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        send_test()
    elif args.once:
        run_check()
    else:
        run_loop()


if __name__ == "__main__":
    main()

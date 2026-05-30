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
    ok, reason = app.is_entry_chance(setup, result.event_risk, config)
    state = app.load_notification_state()
    now = datetime.now(app.JST)

    if not ok:
        state["last_status"] = reason
        state["last_checked_at"] = now.isoformat()
        if setup.bias == "wait":
            state["last_signal_key"] = ""
        app.save_notification_state(state)
        log(f"skip: {reason}; signal={setup.direction}; score={setup.score}")
        return

    key = app.signal_key(setup)
    last_key = str(state.get("last_signal_key", ""))
    last_sent_at = parse_time(state.get("last_sent_at"))
    cooldown = timedelta(minutes=int(config.get("cooldown_minutes", 180)))
    same_side = key == last_key or last_key.startswith(f"{key}|")

    if same_side and last_sent_at and now - last_sent_at < cooldown:
        state["last_status"] = "cooldown"
        state["last_checked_at"] = now.isoformat()
        app.save_notification_state(state)
        log(f"skip: cooldown; signal={setup.direction}; score={setup.score}")
        return

    title, message = app.build_notification_message(result)
    priority = "high" if setup.score >= int(config.get("score_threshold", 68)) + 8 else "default"
    app.send_ntfy_notification(str(config.get("topic", "")), title, message, priority=priority)

    state.update(
        {
            "last_signal_key": key,
            "last_sent_at": now.isoformat(),
            "last_checked_at": now.isoformat(),
            "last_status": "sent",
            "last_title": title,
            "last_message": message,
        }
    )
    app.save_notification_state(state)
    log(f"sent: {title}")


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

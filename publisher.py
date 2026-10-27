#!/usr/bin/env python3
"""Post the next queued deal to @Angebote3 when a Berlin-time slot is due.

Runs once per call (GitHub Actions cron). State lives in state/posted.json,
which the workflow commits back so nothing is posted twice.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Europe/Berlin")
CHANNEL_URL = "https://t.me/Angebote3"
ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)", re.I)
DAY_START, EVENING, LAST = 9 * 60, 20 * 60, 23 * 60 + 30


def slots_for(day) -> list[datetime]:
    minutes = list(range(DAY_START, EVENING, 15)) + list(range(EVENING, LAST + 1, 10))
    return [datetime(day.year, day.month, day.day, m // 60, m % 60, tzinfo=TZ) for m in minutes]


def due_slot(now: datetime) -> datetime | None:
    """Latest slot not later than now, as long as its window is still open."""
    local = now.astimezone(TZ)
    past = [s for s in slots_for(local.date()) if s <= local]
    if not past:
        return None
    slot = past[-1]
    window = timedelta(minutes=15 if slot.hour * 60 + slot.minute < EVENING else 10)
    if local.hour * 60 + local.minute > LAST and slot.hour * 60 + slot.minute == LAST:
        window = timedelta(minutes=1)  # nothing after 23:30
    return slot if local < slot + window else None


def in_posting_hours(now: datetime) -> bool:
    local = now.astimezone(TZ)
    return DAY_START <= local.hour * 60 + local.minute <= LAST


def fmt_price(value: object) -> str:
    try:
        amount = Decimal(str(value).replace("€", "").replace(",", ".").strip())
    except InvalidOperation as error:
        raise ValueError(f"سعر غير صالح: {value}") from error
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"سعر غير صالح: {value}")
    return f"{amount:.2f}"


def deal_key(deal: dict) -> str:
    match = ASIN_RE.search(deal["link"])
    return (deal.get("asin") or (match.group(1) if match else deal["link"])).upper()


def image_for(deal: dict) -> str | None:
    if deal.get("image_url"):
        return deal["image_url"]
    asin = deal.get("asin") or (m.group(1) if (m := ASIN_RE.search(deal["link"])) else None)
    return f"https://m.media-amazon.com/images/P/{asin.upper()}.01._SCRMZZZZZZ_.jpg" if asin else None


def caption(deal: dict) -> str:
    title = str(deal.get("title", "")).strip()
    link = str(deal.get("link", "")).strip()
    if not title or "\n" in title or not link.startswith("https://"):
        raise ValueError("العنوان أو الرابط ناقص")
    now, before = fmt_price(deal["price_now"]), fmt_price(deal["price_before"])
    if Decimal(now) >= Decimal(before):
        raise ValueError("السعر الحالي ليس أقل من السعر السابق")
    text = (
        "🔺عروض يومية || Tägliche Angebote\n\n"
        f"▪ {title}\n\n"
        f"▪ بسعر {now}€ بدل {before}€\n\n"
        f"{link}\n\n"
        "▪ رابط الانضمام إلى القناة 🔗📲📣\n\n"
        f"{CHANNEL_URL}"
    )
    if len(text) > 1024:
        raise ValueError("النص أطول من 1024 حرفاً")
    return text


def read_deals(path: Path) -> list[dict]:
    deals = []
    if not path.is_file():
        return deals
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.strip() and not line.lstrip().startswith("#"):
            try:
                deals.append(json.loads(line))
            except json.JSONDecodeError as error:
                print(f"تجاهل السطر {n}: {error}")
    return deals


def load_state(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"slots": {}, "posted": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def next_deal(deals: list[dict], state: dict) -> tuple[str, dict, str] | None:
    for deal in deals:
        try:
            key = deal_key(deal)
            text = caption(deal)
        except (KeyError, ValueError) as error:
            print(f"عرض مرفوض: {error}")
            continue
        if key in state["posted"]:
            continue
        if not image_for(deal):
            print(f"عرض بلا صورة، تم تجاوزه: {key}")
            continue
        return key, deal, text
    return None


def send_photo(token: str, chat: str, photo: str, text: str) -> int:
    response = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                             data={"chat_id": chat, "photo": photo, "caption": text}, timeout=30)
    payload = response.json()
    if not payload.get("ok"):
        raise PermissionError(payload.get("description", f"HTTP {response.status_code}"))
    return int(payload["result"]["message_id"])


def post_one(deals_path: Path, state_path: Path, slot_label: str, token: str, chat: str) -> str:
    state = load_state(state_path)
    if slot_label in state["slots"]:
        return "slot_used"
    picked = next_deal(read_deals(deals_path), state)
    if not picked:
        print("لا يوجد عرض جديد في القائمة")
        return "queue_empty"
    key, deal, text = picked
    # Reserve before sending: a timeout may still mean Telegram published it.
    state["slots"][slot_label] = key
    state["posted"][key] = {"slot": slot_label, "status": "pending"}
    save_state(state_path, state)
    try:
        message_id = send_photo(token, chat, image_for(deal), text)
    except PermissionError as error:
        # Telegram answered with a clear refusal: nothing was posted.
        del state["slots"][slot_label]
        state["posted"][key] = {"slot": slot_label, "status": "failed", "error": str(error)[:200]}
        save_state(state_path, state)
        print(f"رفض تلغرام العرض {key}: {error}")
        return "failed"
    except Exception as error:
        state["posted"][key]["status"] = "uncertain"
        save_state(state_path, state)
        print(f"نتيجة غير مؤكدة للعرض {key}: {str(error).replace(token, '[T]')[:200]}")
        return "uncertain"
    state["posted"][key] = {"slot": slot_label, "status": "sent", "message_id": message_id}
    save_state(state_path, state)
    print(f"نُشر {key} في {slot_label}")
    return "sent"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["tick", "now", "test", "preview", "schedule"])
    parser.add_argument("--deals", default="deals.jsonl")
    parser.add_argument("--state", default="state/posted.json")
    args = parser.parse_args()
    now = datetime.now(TZ)
    if args.command == "schedule":
        slots = slots_for(now.date())
        print(f"{len(slots)} موعداً: " + ", ".join(s.strftime("%H:%M") for s in slots))
        return 0
    if args.command == "preview":
        picked = next_deal(read_deals(Path(args.deals)), load_state(Path(args.state)))
        print(picked[2] if picked else "لا يوجد عرض جديد في القائمة")
        return 0
    if args.command == "tick":
        slot = due_slot(now)
        if not slot:
            print("ليس موعد نشر الآن")
            return 0
        label = slot.strftime("%Y-%m-%dT%H:%M")
    elif args.command == "test":
        label = now.strftime("%Y-%m-%dT%H:%M") + "-test"
    else:
        if not in_posting_hours(now):
            print("خارج ساعات النشر (09:00 إلى 23:30 بتوقيت برلين)")
            return 0
        label = now.strftime("%Y-%m-%dT%H:%M") + "-manual"
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN غير موجود")
        return 1
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or "@Angebote3"
    post_one(Path(args.deals), Path(args.state), label, token, chat)
    return 0


if __name__ == "__main__":
    sys.exit(main())

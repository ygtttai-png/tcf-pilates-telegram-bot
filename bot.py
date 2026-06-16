import hashlib
import json
import logging
import os
from datetime import datetime
from html import unescape
from typing import Any

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


API_URL = "https://www.tcf.gov.tr/wp-json/wp/v2/posts?per_page=10&orderby=date&order=desc"
PILATES_PAGE_URL = "https://www.tcf.gov.tr/branslar/pilates/"
REQUEST_TIMEOUT_SECONDS = 20

REDIS_LAST_POST_ID_KEY = "tcf:last_processed_post_id"
REDIS_HTML_HASH_KEY = "tcf:pilates_page_hash"
REDIS_NOTIFIED_POST_PREFIX = "tcf:notified_post:"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def clean_html(value: str | None) -> str:
    if not value:
        return ""

    text = BeautifulSoup(unescape(value), "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())


def normalized(value: str) -> str:
    return clean_html(value).casefold()


def matches_keywords(text: str) -> bool:
    haystack = normalized(text)
    return (
        "pilates" in haystack
        and "2. kademe" in haystack
        and (
            "temel eğitmenlik" in haystack
            or "temel egitmenlik" in haystack
            or "temel eğitim" in haystack
            or "temel egitim" in haystack
            or "kursu" in haystack
        )
    )


def get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def request_json(url: str) -> Any:
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def request_text(url: str) -> str:
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def redis_command(*command: str) -> Any:
    redis_url = os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("KV_REST_API_URL")
    redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("KV_REST_API_TOKEN")

    if not redis_url or not redis_token:
        raise RuntimeError(
            "UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN veya "
            "KV_REST_API_URL/KV_REST_API_TOKEN tanımlı olmalı."
        )

    response = requests.post(
        redis_url.rstrip("/"),
        headers={"Authorization": f"Bearer {redis_token}"},
        json=list(command),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()

    if "error" in payload and payload["error"]:
        raise RuntimeError(f"Redis hatası: {payload['error']}")

    return payload.get("result")


def get_redis_value(key: str) -> str | None:
    value = redis_command("GET", key)
    if value is None:
        return None
    return str(value)


def set_redis_value(key: str, value: str) -> None:
    redis_command("SET", key, value)


def set_redis_value_once(key: str, value: str) -> bool:
    return redis_command("SET", key, value, "NX") == "OK"


def send_telegram_message(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID tanımlı olmalı.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": False,
    }

    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return True


def send_error_message(error: Exception) -> None:
    try:
        send_telegram_message(
            "TCF Pilates takip botunda hata oluştu:\n"
            f"{type(error).__name__}: {error}"
        )
    except Exception:
        logging.exception("Hata mesajı Telegram'a gönderilemedi.")


def format_date(date_value: str) -> str:
    if not date_value:
        return "-"

    try:
        parsed = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        return parsed.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return date_value


def shorten(text: str, limit: int = 500) -> str:
    text = clean_html(text)
    if len(text) <= limit:
        return text or "-"
    return text[: limit - 3].rstrip() + "..."


def post_id(post: dict[str, Any]) -> int:
    try:
        return int(post.get("id", 0))
    except (TypeError, ValueError):
        return 0


def post_to_text(post: dict[str, Any]) -> str:
    title = clean_html(post.get("title", {}).get("rendered", ""))
    excerpt = clean_html(post.get("excerpt", {}).get("rendered", ""))
    content = clean_html(post.get("content", {}).get("rendered", ""))
    categories = " ".join(str(category) for category in post.get("categories", []))
    return " ".join([title, excerpt, content, categories])


def build_post_message(post: dict[str, Any]) -> str:
    title = clean_html(post.get("title", {}).get("rendered", "-"))
    excerpt = shorten(post.get("excerpt", {}).get("rendered", ""))
    date = format_date(str(post.get("date", "")))
    link = post.get("link", "-")

    return (
        "🚨 Yeni Pilates 2. Kademe Kurs Duyurusu!\n\n"
        f"Başlık: {title}\n"
        f"Tarih: {date}\n"
        f"Link: {link}\n\n"
        f"Kısa özet: {excerpt}"
    )


def check_api_posts() -> dict[str, int]:
    posts = request_json(API_URL)
    if not isinstance(posts, list):
        raise ValueError("WordPress API beklenen liste formatında cevap vermedi.")

    last_processed_raw = get_redis_value(REDIS_LAST_POST_ID_KEY)
    last_processed_id = int(last_processed_raw) if last_processed_raw else None
    notify_existing = get_bool_env("NOTIFY_EXISTING_ON_FIRST_RUN", False)

    valid_posts = [post for post in posts if post_id(post) > 0]
    if not valid_posts:
        return {"checked": 0, "notified": 0}

    latest_seen_id = max(post_id(post) for post in valid_posts)
    if last_processed_id is None and not notify_existing:
        set_redis_value(REDIS_LAST_POST_ID_KEY, str(latest_seen_id))
        return {"checked": len(valid_posts), "notified": 0}

    new_posts = [
        post
        for post in valid_posts
        if last_processed_id is None or post_id(post) > last_processed_id
    ]

    notified = 0
    for post in sorted(new_posts, key=post_id):
        current_post_id = post_id(post)
        if not matches_keywords(post_to_text(post)):
            continue

        notification_key = f"{REDIS_NOTIFIED_POST_PREFIX}{current_post_id}"
        if not set_redis_value_once(notification_key, "1"):
            continue

        send_telegram_message(build_post_message(post))
        notified += 1

    set_redis_value(REDIS_LAST_POST_ID_KEY, str(latest_seen_id))
    return {"checked": len(valid_posts), "notified": notified}


def build_html_message(page_text: str) -> str:
    return (
        "🚨 Pilates sayfasında 2. Kademe kurs eşleşmesi bulundu!\n\n"
        f"Link: {PILATES_PAGE_URL}\n\n"
        f"Kısa özet: {shorten(page_text)}"
    )


def check_pilates_page() -> dict[str, int | bool]:
    html = request_text(PILATES_PAGE_URL)
    page_text = clean_html(html)

    if not matches_keywords(page_text):
        return {"matched": False, "notified": 0}

    digest = hashlib.sha256(normalized(page_text).encode("utf-8")).hexdigest()
    previous_digest = get_redis_value(REDIS_HTML_HASH_KEY)

    if previous_digest == digest:
        return {"matched": True, "notified": 0}

    set_redis_value(REDIS_HTML_HASH_KEY, digest)
    send_telegram_message(build_html_message(page_text))
    return {"matched": True, "notified": 1}


def run_check() -> dict[str, Any]:
    api_result = check_api_posts()
    html_result = check_pilates_page()
    return {
        "ok": True,
        "api": api_result,
        "html": html_result,
    }


if __name__ == "__main__":
    load_dotenv()
    print(json.dumps(run_check(), ensure_ascii=False, indent=2))

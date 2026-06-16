import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from html import unescape
from typing import Any

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


API_URL = "https://www.tcf.gov.tr/wp-json/wp/v2/posts?per_page=10&orderby=date&order=desc"
PILATES_PAGE_URL = "https://www.tcf.gov.tr/branslar/pilates/"
REQUEST_TIMEOUT_SECONDS = 20
ERROR_THROTTLE_SECONDS = 6 * 60 * 60

TCF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,*/*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": PILATES_PAGE_URL,
}

REDIS_LAST_POST_ID_KEY = "tcf:last_processed_post_id"
REDIS_NOTIFIED_POST_PREFIX = "tcf:notified_post:"
REDIS_HTML_FALLBACK_PREFIX = "tcf:html_fallback:"
REDIS_STARTUP_NOTIFIED_KEY = "tcf:startup_notified"
REDIS_ERROR_STATE_KEY = "tcf:last_error_state"
REDIS_ERROR_THROTTLE_PREFIX = "tcf:error_reported:"


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


def present(value: str | None) -> str:
    return "Present" if value else "Missing"


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def create_tcf_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(TCF_HEADERS)
    return session


def request_json(session: requests.Session, url: str) -> Any:
    logging.info("Fetching WordPress API with browser-like headers.")
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    logging.info("WordPress API response status: %s", response.status_code)
    response.raise_for_status()
    return response.json()


def request_text(session: requests.Session, url: str) -> str:
    logging.info("Fetching HTML fallback page with browser-like headers.")
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    logging.info("HTML fallback response status: %s", response.status_code)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def get_upstash_rest_url() -> str:
    redis_url = (os.getenv("UPSTASH_REDIS_REST_URL") or "").strip()
    if not redis_url:
        raise RuntimeError("UPSTASH_REDIS_REST_URL is Missing.")

    if not redis_url.startswith("https://"):
        raise RuntimeError(
            "UPSTASH_REDIS_REST_URL must be the Upstash REST URL starting with "
            "https://, not the redis:// endpoint."
        )

    return redis_url.rstrip("/")


def get_upstash_rest_token() -> str:
    redis_token = (os.getenv("UPSTASH_REDIS_REST_TOKEN") or "").strip()
    if not redis_token:
        raise RuntimeError("UPSTASH_REDIS_REST_TOKEN is Missing.")
    return redis_token


def redis_command(*command: str) -> Any:
    redis_url = get_upstash_rest_url()
    redis_token = get_upstash_rest_token()

    logging.info("Running Redis command: %s", command[0])
    response = requests.post(
        redis_url,
        headers={"Authorization": f"Bearer {redis_token}"},
        json=list(command),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("error"):
        raise RuntimeError(f"Redis error: {payload['error']}")

    return payload.get("result")


def get_redis_value(key: str) -> str | None:
    value = redis_command("GET", key)
    if value is None:
        return None
    return str(value)


def set_redis_value(key: str, value: str) -> None:
    redis_command("SET", key, value)


def delete_redis_value(key: str) -> None:
    redis_command("DEL", key)


def set_redis_value_once(key: str, value: str, ex_seconds: int | None = None) -> bool:
    command = ["SET", key, value]
    if ex_seconds is not None:
        command.extend(["EX", str(ex_seconds)])
    command.append("NX")
    return redis_command(*command) == "OK"


def send_telegram_message(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID tanımlı olmalı.")

    logging.info("Sending Telegram message.")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def build_startup_message(source_used: str) -> str:
    return (
        "✅ TCF Pilates Bot Started\n\n"
        f"UTC time: {utc_now_text()}\n"
        f"Telegram token: {present(os.getenv('TELEGRAM_BOT_TOKEN'))}\n"
        f"Redis URL: {present(os.getenv('UPSTASH_REDIS_REST_URL'))}\n"
        f"Redis token: {present(os.getenv('UPSTASH_REDIS_REST_TOKEN'))}\n"
        f"Source used: {source_used}"
    )


def send_startup_notification_once(source_used: str) -> None:
    if set_redis_value_once(REDIS_STARTUP_NOTIFIED_KEY, utc_now_text()):
        logging.info("Startup notification has not been sent before; sending now.")
        send_telegram_message(build_startup_message(source_used))
    else:
        logging.info("Startup notification already sent; skipping.")


def send_recovery_notification_if_needed() -> None:
    previous_error = get_redis_value(REDIS_ERROR_STATE_KEY)
    if not previous_error:
        logging.info("No previous error state found.")
        return

    delete_redis_value(REDIS_ERROR_STATE_KEY)
    logging.info("Previous error state cleared; sending recovery notification.")
    send_telegram_message("✅ Bot recovered successfully")


def error_signature(error: Exception) -> str:
    raw = f"{type(error).__name__}:{error}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_error_message(error: Exception) -> str:
    return (
        "TCF Pilates takip botunda hata oluştu:\n"
        f"{type(error).__name__}: {error}\n\n"
        f"UTC time: {utc_now_text()}"
    )


def report_error_once(error: Exception) -> None:
    try:
        signature = error_signature(error)
        throttle_key = f"{REDIS_ERROR_THROTTLE_PREFIX}{signature}"
        set_redis_value(REDIS_ERROR_STATE_KEY, signature)

        if not set_redis_value_once(throttle_key, utc_now_text(), ERROR_THROTTLE_SECONDS):
            logging.info("Same error was already reported in the last 6 hours; skipping Telegram alert.")
            return

        logging.info("Reporting new or unthrottled error to Telegram.")
        send_telegram_message(build_error_message(error))
    except Exception as redis_error:
        logging.exception("Redis error throttling failed; sending direct Telegram error for this run.")
        send_telegram_message(
            build_error_message(error)
            + "\n\nError throttling failed:\n"
            + f"{type(redis_error).__name__}: {redis_error}"
        )


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
    return " ".join([title, excerpt, content])


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


def build_html_fallback_message(page_text: str) -> str:
    return (
        "🚨 Pilates sayfasında 2. Kademe kurs eşleşmesi bulundu!\n\n"
        f"Link: {PILATES_PAGE_URL}\n\n"
        f"Kısa özet: {shorten(page_text)}"
    )


def check_api_posts(session: requests.Session) -> dict[str, int | str]:
    posts = request_json(session, API_URL)
    if not isinstance(posts, list):
        raise ValueError("WordPress API beklenen liste formatında cevap vermedi.")

    valid_posts = [post for post in posts if post_id(post) > 0]
    logging.info("Fetched %s valid posts from WordPress API.", len(valid_posts))
    if not valid_posts:
        return {
            "source_used": "WordPress API",
            "checked": 0,
            "new_posts": 0,
            "matched": 0,
            "notified": 0,
        }

    last_processed_raw = get_redis_value(REDIS_LAST_POST_ID_KEY)
    last_processed_id = int(last_processed_raw) if last_processed_raw else None
    latest_seen_id = max(post_id(post) for post in valid_posts)

    logging.info("Last processed post id: %s", last_processed_id)
    logging.info("Latest seen post id: %s", latest_seen_id)

    if last_processed_id is None and not get_bool_env("NOTIFY_EXISTING_ON_FIRST_RUN"):
        set_redis_value(REDIS_LAST_POST_ID_KEY, str(latest_seen_id))
        logging.info("First run: saved latest post id as baseline.")
        return {
            "source_used": "WordPress API",
            "checked": len(valid_posts),
            "new_posts": 0,
            "matched": 0,
            "notified": 0,
        }

    new_posts = [
        post
        for post in valid_posts
        if last_processed_id is None or post_id(post) > last_processed_id
    ]

    logging.info("New posts to inspect: %s", len(new_posts))
    matched = 0
    notified = 0
    for post in sorted(new_posts, key=post_id):
        current_post_id = post_id(post)
        title = clean_html(post.get("title", {}).get("rendered", ""))
        logging.info("Inspecting post %s: %s", current_post_id, title)

        if not matches_keywords(post_to_text(post)):
            logging.info("Post %s did not match keywords.", current_post_id)
            continue

        matched += 1
        notification_key = f"{REDIS_NOTIFIED_POST_PREFIX}{current_post_id}"
        if not set_redis_value_once(notification_key, "1"):
            logging.info("Post %s was already notified; skipping.", current_post_id)
            continue

        send_telegram_message(build_post_message(post))
        logging.info("Telegram notification sent for post %s.", current_post_id)
        notified += 1

    set_redis_value(REDIS_LAST_POST_ID_KEY, str(latest_seen_id))
    logging.info("Saved last processed post id: %s", latest_seen_id)
    return {
        "source_used": "WordPress API",
        "checked": len(valid_posts),
        "new_posts": len(new_posts),
        "matched": matched,
        "notified": notified,
    }


def check_html_fallback(session: requests.Session) -> dict[str, int | str]:
    html = request_text(session, PILATES_PAGE_URL)
    page_text = clean_html(html)
    logging.info("HTML fallback text length: %s", len(page_text))

    if not matches_keywords(page_text):
        logging.info("HTML fallback did not match keywords.")
        return {
            "source_used": "HTML fallback",
            "checked": 1,
            "new_posts": 0,
            "matched": 0,
            "notified": 0,
        }

    digest = hashlib.sha256(normalized(page_text).encode("utf-8")).hexdigest()
    notification_key = f"{REDIS_HTML_FALLBACK_PREFIX}{digest}"

    if not set_redis_value_once(notification_key, "1"):
        logging.info("HTML fallback match was already notified; skipping.")
        return {
            "source_used": "HTML fallback",
            "checked": 1,
            "new_posts": 1,
            "matched": 1,
            "notified": 0,
        }

    send_telegram_message(build_html_fallback_message(page_text))
    logging.info("Telegram notification sent for HTML fallback match.")
    return {
        "source_used": "HTML fallback",
        "checked": 1,
        "new_posts": 1,
        "matched": 1,
        "notified": 1,
    }


def check_posts() -> dict[str, int | str]:
    session = create_tcf_session()
    try:
        return check_api_posts(session)
    except requests.RequestException as exc:
        logging.warning("WordPress API failed; using HTML fallback. Error: %s", exc)
        return check_html_fallback(session)
    except ValueError as exc:
        logging.warning("WordPress API response was invalid; using HTML fallback. Error: %s", exc)
        return check_html_fallback(session)


def main() -> None:
    load_dotenv()
    logging.info("TCF Pilates bot run started.")
    logging.info("UTC start time: %s", utc_now_text())
    logging.info("Telegram token: %s", present(os.getenv("TELEGRAM_BOT_TOKEN")))
    logging.info("Telegram chat id: %s", present(os.getenv("TELEGRAM_CHAT_ID")))
    logging.info("Redis URL: %s", present(os.getenv("UPSTASH_REDIS_REST_URL")))
    logging.info("Redis token: %s", present(os.getenv("UPSTASH_REDIS_REST_TOKEN")))

    try:
        result = check_posts()
        source_used = str(result["source_used"])
        send_startup_notification_once(source_used)
        send_recovery_notification_if_needed()
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    except Exception as exc:
        logging.exception("Bot run failed. Original error: %s", exc)
        try:
            report_error_once(exc)
        except Exception:
            logging.exception("Direct Telegram error alert also failed.")
        raise


if __name__ == "__main__":
    main()

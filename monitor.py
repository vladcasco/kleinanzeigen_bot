import os
import json
import time
import requests
from bs4 import BeautifulSoup

# =========================================================
# НАСТРОЙ ЭТИ ССЫЛКИ ПОД СЕБЯ
# Зайди на kleinanzeigen.de, введи ключевые слова + город/фильтры,
# скопируй итоговый URL из адресной строки и вставь сюда.
# Можно добавить сколько угодно ссылок в список.
# =========================================================
SEARCH_URLS = [
    "https://www.kleinanzeigen.de/s-villeroy-boch/k0",
    "https://www.kleinanzeigen.de/s-geschirr-zu-verschenken/k0",
]

STATE_FILE = "seen_ads.json"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}


def load_seen():
    """Возвращает None при первом запуске (файла ещё нет),
    иначе множество уже увиденных id объявлений."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return None


def save_seen(seen_ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f, ensure_ascii=False, indent=2)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    if not resp.ok:
        print("Ошибка отправки в Telegram:", resp.text)


def fetch_listings(search_url):
    resp = requests.get(search_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    listings = []
    items = soup.select("li.ad-listitem[data-adid]") or soup.select("article.aditem")

    for item in items:
        ad_id = item.get("data-adid")
        link_tag = item.select_one("a.ellipsis") or item.select_one("h2 a")
        if not ad_id or not link_tag:
            continue

        title = link_tag.get_text(strip=True)
        href = link_tag.get("href", "")
        full_url = "https://www.kleinanzeigen.de" + href if href.startswith("/") else href

        price_tag = item.select_one("p.aditem-main--middle--price-shipping--price")
        price = price_tag.get_text(strip=True) if price_tag else ""

        desc_tag = item.select_one("p.aditem-main--middle--description")
        desc = desc_tag.get_text(strip=True) if desc_tag else ""

        location_tag = item.select_one("div.aditem-main--top--left")
        location = location_tag.get_text(strip=True) if location_tag else ""

        listings.append(
            {
                "id": ad_id,
                "title": title,
                "url": full_url,
                "price": price,
                "desc": desc,
                "location": location,
            }
        )

    return listings


def main():
    seen = load_seen()
    first_run = seen is None
    if seen is None:
        seen = set()

    all_current_ids = set()
    new_items = []

    for url in SEARCH_URLS:
        try:
            listings = fetch_listings(url)
        except Exception as e:
            print(f"Ошибка при загрузке {url}: {e}")
            continue

        for item in listings:
            all_current_ids.add(item["id"])
            if item["id"] not in seen:
                new_items.append(item)

    if first_run:
        # В первый запуск просто запоминаем всё, что уже есть на сайте,
        # чтобы не получить сразу пачку "старых" уведомлений
        print(f"Первый запуск: сохранено {len(all_current_ids)} объявлений без уведомлений.")
    else:
        for item in new_items:
            text = (
                f"🆕 <b>{item['title']}</b>\n"
                f"💶 {item['price']}\n"
                f"📍 {item['location']}\n"
                f"{item['desc'][:200]}\n"
                f"{item['url']}"
            )
            send_telegram(text)
            time.sleep(1)
        print(f"Найдено новых объявлений: {len(new_items)}")

    save_seen(all_current_ids | seen)


if __name__ == "__main__":
    main()

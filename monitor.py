import os
import html
import json
import time
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator

# =========================================================
# Поиски: подпись (для группировки на странице) + ссылка
# =========================================================
SEARCHES = [
    {"label": "Посуда (общее)", "url": "https://www.kleinanzeigen.de/s-muenchen/geschirr/k0l6411r50"},
    {"label": "Villeroy & Boch", "url": "https://www.kleinanzeigen.de/s-muenchen/villeroy-boch/k0l6411r50"},
    {"label": "Rosenthal", "url": "https://www.kleinanzeigen.de/s-muenchen/rosenthal/k0l6411r50"},
    {"label": "Отдать даром", "url": "https://www.kleinanzeigen.de/s-muenchen/geschirr-zu-verschenken/k0l6411r50"},
    {"label": "Винтажный фарфор", "url": "https://www.kleinanzeigen.de/s-muenchen/porzellan-vintage/k0l6411r50"},
]

SEEN_FILE = "seen_ads.json"          # id всех объявлений, которые уже видели (для отметки "новое")
CACHE_FILE = "translations_cache.json"  # кэш переводов, чтобы не переводить одно и то же заново
PAGE_FILE = "docs/index.html"        # страница со всеми объявлениями (публикуется через GitHub Pages)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}

translator = GoogleTranslator(source="de", target="ru")


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def translate_text(text, cache):
    """Переводит текст на русский, кэшируя результат, чтобы не дёргать
    сервис перевода повторно для уже переведённых фраз."""
    text = (text or "").strip()
    if not text:
        return text
    if text in cache:
        return cache[text]
    try:
        translated = translator.translate(text)
        if not translated:
            translated = text
    except Exception as e:
        print(f"Не удалось перевести '{text}': {e}")
        translated = text  # если перевод не сработал — оставляем как есть
    cache[text] = translated
    return translated


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

    # --- ВРЕМЕННАЯ ДИАГНОСТИКА ---
    print(
        f"[debug] {search_url} -> HTTP {resp.status_code}, "
        f"размер ответа: {len(resp.text)} байт, найдено элементов: {len(items)}"
    )
    if len(items) == 0:
        lower = resp.text.lower()
        markers = [
            "data-adid", "adid", "ad-listitem", "aditem",
            "__next_data__", "srchrslt", "search-result",
            '"ads":', '"items":', '"results":', "articleid",
        ]
        counts = {m: lower.count(m) for m in markers}
        print(f"[debug] Маркеры в ответе: {counts}")

        idx = lower.find("adid")
        if idx != -1:
            context = resp.text[max(0, idx - 150): idx + 350].replace("\n", " ")
            print(f"[debug] Контекст вокруг 'adid': ...{context}...")
        else:
            print("[debug] Подстрока 'adid' вообще не найдена в ответе — данные объявлений, "
                  "видимо, закодированы иначе или подгружаются отдельным запросом.")
    # --- КОНЕЦ ДИАГНОСТИКИ ---

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

        location_tag = item.select_one("div.aditem-main--top--left")
        location = location_tag.get_text(strip=True) if location_tag else ""

        listings.append(
            {
                "id": ad_id,
                "title": title,
                "url": full_url,
                "price": price,
                "location": location,
            }
        )

    return listings


def render_page(sections):
    now = time.strftime("%d.%m.%Y %H:%M UTC", time.gmtime())
    parts = [f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kleinanzeigen — Посуда, Мюнхен +50 км</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; max-width: 860px; margin: 0 auto;
          padding: 16px; background: #fafafa; color: #222; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  h2 {{ font-size: 18px; margin-top: 32px; border-bottom: 2px solid #ddd; padding-bottom: 4px; }}
  .updated {{ color: #777; font-size: 13px; margin-bottom: 24px; }}
  .item {{ display: block; background: #fff; border: 1px solid #eee; border-radius: 8px;
           padding: 12px 16px; margin-bottom: 10px; }}
  .item.new {{ border-color: #4caf50; background: #f2fff2; }}
  .badge {{ display: inline-block; background: #4caf50; color: #fff; font-size: 11px;
            padding: 2px 8px; border-radius: 10px; margin-right: 8px; }}
  .title {{ font-weight: 600; font-size: 15px; }}
  .price {{ color: #d35400; font-weight: 600; margin-top: 4px; }}
  .meta {{ color: #888; font-size: 13px; margin-top: 4px; }}
  a.item {{ color: inherit; text-decoration: none; }}
  .empty {{ color: #999; font-style: italic; }}
</style>
</head>
<body>
<h1>🍽 Kleinanzeigen — Посуда (Мюнхен +50 км)</h1>
<div class="updated">Обновлено: {now}</div>
"""]

    for section in sections:
        parts.append(f"<h2>{html.escape(section['label'])} ({len(section['items'])})</h2>")
        if not section["items"]:
            parts.append('<p class="empty">Пока ничего не найдено.</p>')
        for item in section["items"]:
            cls = "item new" if item["is_new"] else "item"
            badge = '<span class="badge">НОВОЕ</span>' if item["is_new"] else ""
            parts.append(f"""
<a class="{cls}" href="{html.escape(item['url'])}" target="_blank" rel="noopener">
  {badge}<span class="title">{html.escape(item['title_ru'])}</span>
  <div class="price">{html.escape(item['price_ru'])}</div>
  <div class="meta">{html.escape(item['location'])}</div>
</a>""")

    parts.append("</body></html>")

    directory = os.path.dirname(PAGE_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(PAGE_FILE, "w", encoding="utf-8") as f:
        f.write("".join(parts))


def main():
    first_run = not os.path.exists(SEEN_FILE)
    seen_ids = set(load_json(SEEN_FILE, []))
    cache = load_json(CACHE_FILE, {})

    sections = []
    new_items_for_telegram = []
    all_current_ids = set()

    for search in SEARCHES:
        try:
            listings = fetch_listings(search["url"])
        except Exception as e:
            print(f"Ошибка при загрузке {search['url']}: {e}")
            listings = []

        section_items = []
        for item in listings:
            all_current_ids.add(item["id"])
            is_new = item["id"] not in seen_ids

            title_ru = translate_text(item["title"], cache)
            price_ru = translate_text(item["price"], cache)

            enriched = {**item, "title_ru": title_ru, "price_ru": price_ru, "is_new": is_new}
            section_items.append(enriched)

            if is_new and not first_run:
                new_items_for_telegram.append(enriched)

        # новые объявления показываем сверху секции
        section_items.sort(key=lambda x: not x["is_new"])
        sections.append({"label": search["label"], "items": section_items})

    for item in new_items_for_telegram:
        text = (
            f"🆕 <b>{item['title_ru']}</b>\n"
            f"💶 {item['price_ru']}\n"
            f"📍 {item['location']}\n"
            f"{item['url']}"
        )
        send_telegram(text)
        time.sleep(1)

    if first_run:
        print(f"Первый запуск: сохранено {len(all_current_ids)} объявлений, страница создана без уведомлений.")
    else:
        print(f"Найдено новых объявлений: {len(new_items_for_telegram)}")

    save_json(SEEN_FILE, sorted(all_current_ids))
    save_json(CACHE_FILE, cache)
    render_page(sections)


if __name__ == "__main__":
    main()

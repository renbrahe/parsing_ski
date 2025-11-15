import time
import csv
import re
import os
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.xtreme.ge/en/shop/category/ski-skis-2"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------- НАСТРОЙКИ РЕЖИМА ОБХОДА СТРАНИЦ ----------

TEST_MODE = True
TEST_MAX_PAGES = 1

CSV_FILENAME = "xtreme_ski_table.csv"
SHOP_NAME = "xtreme.ge"


def get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def build_page_url(base_url: str, page: int) -> str:
    parsed = urlparse(base_url)
    q = parse_qs(parsed.query)
    q["page"] = [str(page)]
    new_query = urlencode(q, doseq=True)
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)


# ---------- СБОР ССЫЛОК НА ТОВАРЫ ----------

def extract_product_links_from_soup(soup: BeautifulSoup, base_url: str) -> list[str]:
    links: list[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]

        if not href.startswith("/en/shop/"):
            continue
        if "/en/shop/category/" in href:
            continue
        if href.startswith("/en/shop/cart"):
            continue
        if href.startswith("/en/shop/change_pricelist"):
            continue
        if href.startswith("/en/shop/product/"):
            continue

        full_url = urljoin(base_url, href)
        links.append(full_url)

    unique_links = sorted(set(links))
    return unique_links


def parse_all_list_pages(base_url: str, max_pages: int | None = None) -> list[str]:
    all_product_urls: set[str] = set()

    page = 1
    print(f"[INFO] Получаю страницу {page}: {base_url}")
    soup = get_soup(base_url)
    page_links = extract_product_links_from_soup(soup, base_url)
    first_page_count = len(page_links)
    print(f"[INFO] Найдено ссылок на товары на странице {page}: {first_page_count}")

    if first_page_count == 0:
        print("[WARN] На первой странице не найдено ни одной ссылки на товар.")
        try:
            with open("debug_xtreme_page_1.html", "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            print("[DEBUG] HTML первой страницы сохранён в debug_xtreme_page_1.html")
        except Exception as e:
            print(f"[DEBUG] Не удалось сохранить HTML первой страницы: {e}")
        return []

    all_product_urls.update(page_links)

    page = 2
    while True:
        if max_pages is not None and page > max_pages:
            print(f"[INFO] Достигнут лимит страниц: max_pages={max_pages}")
            break

        page_url = build_page_url(base_url, page)
        print(f"[INFO] Получаю страницу {page}: {page_url}")

        try:
            soup = get_soup(page_url)
        except Exception as e:
            print(f"[ERROR] Не удалось загрузить страницу {page}: {e}")
            break

        page_links = extract_product_links_from_soup(soup, base_url)
        count = len(page_links)

        if count == 0:
            print("[INFO] На странице нет ссылок на товары – страниц больше нет.")
            break

        print(f"[INFO] Найдено ссылок на товары на странице {page}: {count}")

        new_links = [u for u in page_links if u not in all_product_urls]
        if not new_links:
            print("[INFO] Новых ссылок на товары не появилось – останавливаемся.")
            break

        all_product_urls.update(new_links)

        page += 1
        time.sleep(1.0)

    return sorted(all_product_urls)


# ---------- ВСПОМОГАТЕЛЬНОЕ: очистка длины и цен ----------

def _clean_length_text(text: str) -> str:
    if not text:
        return ""
    digits = re.sub(r"\D+", "", text)
    return digits or text.strip()


def split_price(text: str) -> tuple[str, str]:
    """
    Разделяем цену на число и валюту.
    Возвращаем (число_как_строка, строка_валюты).
    """
    if not text or text == "N/A":
        return "", ""

    raw = text.strip()
    m = re.search(r"([\d.,]+)", raw)
    number = ""
    if m:
        number = m.group(1).replace(" ", "")

    currency = ""
    if "₾" in raw:
        currency = "GEL"
    else:
        rest = raw.replace(m.group(1), "") if m else raw
        rest = rest.replace("₾", "").strip()
        if rest:
            currency = rest

    return number, currency


# ---------- ПАРСИНГ КАРТОЧКИ ТОВАРА ----------

def parse_product_page(url: str) -> dict:
    """
    Заходим на страницу товара и вытаскиваем:
    бренд, модель, сырые цены (со строками), размеры.
    """
    try:
        soup = get_soup(url)
    except Exception as e:
        print(f"[ERROR] Не удалось загрузить {url}: {e}")
        return {
            "brand": "N/A",
            "model": "N/A",
            "full_name": "N/A",
            "price_new_raw": "N/A",
            "price_old_raw": "N/A",
            "sizes": [],
        }

    # --- бренд / модель ---
    brand_tag = soup.select_one(
        "h1.o_wsale_product_page_title .brand-name-detail span"
    )
    model_tag = soup.select_one(
        "h1.o_wsale_product_page_title .product-name-detail span"
    )

    brand = brand_tag.get_text(strip=True) if brand_tag else "N/A"
    model = model_tag.get_text(strip=True) if model_tag else "N/A"

    if brand == "N/A" and model == "N/A":
        title_tag = soup.find("h1")
        if title_tag:
            parts = [t.strip() for t in title_tag.stripped_strings if t.strip()]
            if len(parts) >= 2:
                brand = parts[0]
                model = " ".join(parts[1:])
            elif len(parts) == 1:
                model = parts[0]

    full_title = f"{brand} {model}".strip() if (brand != "N/A" or model != "N/A") else "N/A"

    # --- цены (сырые строки, дальше разбираем отдельно) ---
    price_new_tag = soup.select_one("div.product_price span.oe_price.text-danger")
    price_old_tag = soup.select_one("div.product_price span.oe_price.text-muted")

    price_new_raw = price_new_tag.get_text(strip=True) if price_new_tag else "N/A"
    price_old_raw = price_old_tag.get_text(strip=True) if price_old_tag else "N/A"

    # fallback, если скидки нет и красной цены нет
    if price_new_raw == "N/A":
        price_new_tag2 = soup.select_one("div.product_price span.oe_price")
        if not price_new_tag2:
            price_new_tag2 = soup.select_one("span[itemprop='price']")
        if price_new_tag2:
            price_new_raw = price_new_tag2.get_text(strip=True)

    # --- размеры ---
    size_main_tags = soup.select("div.main-product-sizes-grid span.main-size-badge")
    size_alt_tags = soup.select(
        "div.alternative-product-sizes-grid span.alternative-size-badge-clickable"
    )

    all_size_texts: list[str] = []
    for t in size_main_tags + size_alt_tags:
        val = t.get("title") or t.get_text(strip=True)
        val = _clean_length_text(val)
        if val:
            all_size_texts.append(val)

    sizes = (
        sorted(
            set(all_size_texts),
            key=lambda x: int(re.sub(r"\D+", "", x) or 0),
        )
        if all_size_texts
        else []
    )

    return {
        "brand": brand if brand else "N/A",
        "model": model if model else "N/A",
        "full_name": full_title if full_title else "N/A",
        "price_new_raw": price_new_raw or "N/A",
        "price_old_raw": price_old_raw or "N/A",
        "sizes": sizes,
    }


# ---------- РАБОТА С CSV ----------

def load_existing_rows(filename: str) -> list[dict]:
    if not os.path.exists(filename):
        return []
    with open(filename, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        return list(reader)


def main():
    max_pages = TEST_MAX_PAGES if TEST_MODE else None
    mode_label = (
        f"ТЕСТОВЫЙ режим: только первые {TEST_MAX_PAGES} страниц"
        if TEST_MODE
        else "БОЕВОЙ режим: обходим все страницы"
    )
    print(f"[INFO] {mode_label}")

    today_str = time.strftime("%Y-%m-%d")
    price_col_today = f"price_new_{today_str}"

    # 1. загружаем существующий CSV
    existing_rows = load_existing_rows(CSV_FILENAME)
    print(f"[INFO] Загружено существующих строк из CSV: {len(existing_rows)}")

    existing_by_key: dict[tuple[str, str], dict] = {}
    known_urls: set[str] = set()
    not_interesting_urls: set[str] = set()

    NOT_INTERESTING_VALUES = {"0", "no", "n", "false", "-", "нет", "не"}

    for row in existing_rows:
        url = row.get("product_url", "")
        size = row.get("size", "")
        if url:
            known_urls.add(url)
        key = (url, size)
        existing_by_key[key] = row

        flag = (row.get("is_interesting", "") or "").strip().lower()
        if url and flag in NOT_INTERESTING_VALUES:
            not_interesting_urls.add(url)

    # 2. получаем все ссылки на товары
    product_urls = parse_all_list_pages(BASE_URL, max_pages=max_pages)
    print(f"\n[INFO] Всего уникальных товаров по ссылкам: {len(product_urls)}")

    # 3. парсим карточки для новых и "интересных" товаров
    for idx, url in enumerate(product_urls, start=1):
        is_new_product = url not in known_urls
        product_interesting = url not in not_interesting_urls  # по умолчанию да

        needs_update = is_new_product or product_interesting

        if not needs_update:
            print(f"[SKIP] ({idx}/{len(product_urls)}) {url} — помечен как неинтересный, пропускаю.")
            continue

        print(f"[DETAIL] ({idx}/{len(product_urls)}) Парсю {url}")
        detail = parse_product_page(url)

        price_new_val, price_new_cur = split_price(detail["price_new_raw"])
        price_old_val, price_old_cur = split_price(detail["price_old_raw"])

        # одна общая валюта
        currency = price_new_cur or price_old_cur or "GEL"

        sizes = detail["sizes"] or ["N/A"]

        for size in sizes:
            key = (url, size)
            row = existing_by_key.get(key)

            if row is None:
                # новая строка — по умолчанию интересна (1)
                is_interesting_val = "0" if url in not_interesting_urls else "1"
                row = {
                    "shop_name": SHOP_NAME,
                    "is_interesting": is_interesting_val,
                    "brand": detail["brand"],
                    "model": detail["model"],
                    "full_name": detail["full_name"],
                    "size": size,
                    "price_old": price_old_val,
                    "currency": currency,
                    "product_url": url,
                }
                existing_rows.append(row)
                existing_by_key[key] = row
            else:
                # обновляем общую инфу
                if detail["brand"] and detail["brand"] != "N/A":
                    row["brand"] = detail["brand"]
                if detail["model"] and detail["model"] != "N/A":
                    row["model"] = detail["model"]
                if detail["full_name"] and detail["full_name"] != "N/A":
                    row["full_name"] = detail["full_name"]

                if price_old_val:
                    row["price_old"] = price_old_val
                if currency:
                    row["currency"] = currency

            # сегодняшнее значение цены
            row[price_col_today] = price_new_val

        time.sleep(0.5)

    # 4. собираем список колонок
    all_fieldnames = set()
    for row in existing_rows:
        all_fieldnames.update(row.keys())

    base_fields = [
        "shop_name",
        "is_interesting",
        "brand",
        "model",
        "full_name",
        "size",
        "price_old",
        "currency",
        "product_url",
    ]
    for bf in base_fields:
        all_fieldnames.add(bf)

    price_cols = sorted([c for c in all_fieldnames if c.startswith("price_new_")])

    fieldnames = (
        ["shop_name", "is_interesting", "brand", "model", "full_name", "size"]
        + ["price_old", "currency"]
        + price_cols
        + ["product_url"]
    )

    # заполняем отсутствующие ключи пустыми строками
    for row in existing_rows:
        for fn in fieldnames:
            row.setdefault(fn, "")

    # 5. сохраняем CSV
    with open(CSV_FILENAME, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in existing_rows:
            writer.writerow(row)

    print(f"\n[OK] Сохранено {len(existing_rows)} строк в файл {CSV_FILENAME}")
    print(f"[OK] Добавлена/обновлена колонка: {price_col_today}")


if __name__ == "__main__":
    main()

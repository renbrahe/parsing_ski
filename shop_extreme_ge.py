# shop_extreme_ge.py
import time
import re
from typing import List, Tuple, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin

import requests
from bs4 import BeautifulSoup

from models import Product


BASE_URL = "https://www.xtreme.ge/en/shop/category/ski-skis-2"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SHOP_NAME = "xtreme.ge"


def get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


# ---------- LIST PAGES ----------


def _normalize_page_url(url: str, base_url: str) -> str:
    """
    Убираем всякий мусор из query-параметров, чтобы ссылки не дублировались.
    """
    parsed = urlparse(url)
    base_parsed = urlparse(base_url)

    # нормализуем схему/домен, если вдруг относительные
    scheme = parsed.scheme or base_parsed.scheme
    netloc = parsed.netloc or base_parsed.netloc

    qs = parse_qs(parsed.query)
    # оставим только минимум нужных параметров, если очень надо
    allowed_keys = {"page", "category_id"}
    qs_filtered = {k: v for k, v in qs.items() if k in allowed_keys}

    new_query = urlencode(qs_filtered, doseq=True)

    normalized = urlunparse(
        (
            scheme,
            netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )
    return normalized


def extract_product_links_from_soup(soup: BeautifulSoup, base_url: str) -> List[str]:
    """
    Из HTML категории вытаскиваем ссылки на карточки товаров.
    Под текущую верстку xtreme (Odoo) товары лежат в .oe_product.
    """
    links: List[str] = []

    # Каждый товар — div.oe_product
    for product in soup.select("div.oe_product"):
        # Основная ссылка — по картинке
        a = product.select_one("a.oe_product_image_link")
        if a is None:
            # fallback — по заголовку
            a = product.select_one("h6.o_wsale_products_item_title a")
        if not a:
            continue

        href = a.get("href")
        if not href:
            continue

        full_url = urljoin(base_url, href)
        # Нормализуем URL (убираем лишние query-параметры и т.п.)
        full_url = _normalize_page_url(full_url, base_url)
        links.append(full_url)

    unique_links = sorted(set(links))
    return unique_links


def parse_all_list_pages(base_url: str, max_pages: Optional[int] = None) -> List[str]:
    all_product_urls: set[str] = set()

    page = 1
    print(f"[INFO] Fetch page {page}: {base_url}")
    soup = get_soup(base_url)
    page_links = extract_product_links_from_soup(soup, base_url)
    first_page_count = len(page_links)
    print(f"[INFO] Found {first_page_count} product links on page {page}")

    if first_page_count == 0:
        print("[WARN] No product links found on first page.")
        try:
            with open("debug_xtreme_page_1.html", "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            print("[DEBUG] Saved HTML of first page to debug_xtreme_page_1.html")
        except Exception as e:
            print(f"[DEBUG] Failed to save first page HTML: {e}")
        return []

    all_product_urls.update(page_links)

    page = 2
    while True:
        if max_pages is not None and page > max_pages:
            print(f"[INFO] Reached max_pages={max_pages}")
            break

        next_url = f"{base_url}?page={page}"
        print(f"[INFO] Fetch page {page}: {next_url}")

        try:
            soup = get_soup(next_url)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            print(f"[INFO] Stop on page={page}, HTTP {status}")
            break
        except Exception as e:
            print(f"[WARN] Failed to fetch page {page}: {e}")
            break

        new_links = extract_product_links_from_soup(soup, base_url)
        if not new_links:
            print(f"[INFO] No product links on page {page}, stop.")
            break

        before = len(all_product_urls)
        all_product_urls.update(new_links)
        after = len(all_product_urls)
        delta = after - before

        print(
            f"[INFO] Page {page}: found {len(new_links)} links, total unique {after} "
            f"(+{delta})"
        )

        # 🔴 ВОТ ЗДЕСЬ ОГРАНИЧИТЕЛЬ: если новых ссылок нет — выходим
        if delta == 0:
            print(f"[INFO] No new unique products on page {page}, stopping pagination.")
            break

        page += 1
        time.sleep(1.0)

    return sorted(all_product_urls)


# ---------- HELPERS: length & price ----------


def _clean_length_text(text: str) -> str:
    if not text:
        return ""
    digits = re.sub(r"\D+", "", text)
    return digits or ""


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


def _price_to_float(value: str) -> Optional[float]:
    if not value:
        return None
    # remove thousands separators, keep decimal point
    normalized = value.replace(" ", "").replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


# ---------- PRODUCT PAGE ----------


def parse_product_page(url: str) -> dict:
    """
    Заходим на страницу товара и вытаскиваем:
    бренд, модель, сырые цены (со строками), размеры.
    """
    try:
        soup = get_soup(url)
    except Exception as e:
        print(f"[ERROR] Failed to load {url}: {e}")
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
            title = " ".join(parts)
            # простая эвристика: попробуем разделить по первому слову
            tokens = title.split()
            if tokens:
                brand = tokens[0]
                model = " ".join(tokens[1:]) if len(tokens) > 1 else "N/A"

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

    sizes = sorted(set(all_size_texts))

    return {
        "brand": brand if brand else "N/A",
        "model": model if model else "N/A",
        "full_name": full_title if full_title else "N/A",
        "price_new_raw": price_new_raw or "N/A",
        "price_old_raw": price_old_raw or "N/A",
        "sizes": sizes,
    }


# ---------- PUBLIC API ----------


def scrape_xtreme(
    test_mode: bool = False,
    max_pages: Optional[int] = None,
) -> List[Product]:
    """
    Основная функция: обходит xtreme.ge и возвращает список Product.

    :param test_mode: если True — берём только первую страницу списка товаров
    :param max_pages: явное ограничение на количество страниц (перебивает test_mode)
    """
    print(f"[INFO] Start scraping {SHOP_NAME}")

    # если включен test_mode и max_pages не задан явно — ограничиваемся 1 страницей
    if test_mode and max_pages is None:
        effective_max_pages = 1
    else:
        effective_max_pages = max_pages

    product_urls = parse_all_list_pages(BASE_URL, max_pages=effective_max_pages)
    print(f"[INFO] Total unique product URLs: {len(product_urls)}")

    products: List[Product] = []

    for idx, url in enumerate(product_urls, start=1):
        print(f"[INFO] [{idx}/{len(product_urls)}] Parse product: {url}")
        detail = parse_product_page(url)

        price_new_num, currency = split_price(detail["price_new_raw"])
        price_old_num, _ = split_price(detail["price_old_raw"])

        current_price = _price_to_float(price_new_num)
        old_price = _price_to_float(price_old_num)

        sizes = detail.get("sizes") or []
        if not sizes:
            sizes = [""]

        for size in sizes:
            p = Product(
                shop=SHOP_NAME,
                url=url,
                brand=None if detail["brand"] == "N/A" else detail["brand"],
                model=None if detail["model"] == "N/A" else detail["model"],
                title=None if detail["full_name"] == "N/A" else detail["full_name"],
                sizes=[size] if size else [],
                current_price=current_price,
                old_price=old_price,
                currency=currency or "GEL",
                in_stock=True,
                quantity=None,
                shop_sku=None,
                condition="new",
            )
            products.append(p)

        time.sleep(0.3)

    print(f"[OK] Finished {SHOP_NAME}, total rows: {len(products)}")
    return products



if __name__ == "__main__":
    # standalone debug run
    res = scrape_xtreme(test_mode=True)  # одна страница
    print(f"Scraped {len(res)} rows from {SHOP_NAME}")


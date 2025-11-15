import csv
import time
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DOMAIN = "https://snowmania.ge"

# Парсим только эти две категории (новые и б/у лыжи)
CATEGORY_URLS: List[Tuple[str, str]] = [
    (
        "https://snowmania.ge/product-category/%e1%83%90%e1%83%ae%e1%83%90%e1%83%9a%e1%83%98/%e1%83%97%e1%83%ae%e1%83%98%e1%83%9a%e1%83%90%e1%83%9b%e1%83%a3%e1%83%a0%e1%83%98/",
        "new",
    ),
    (
        "https://snowmania.ge/product-category/%e1%83%9b%e1%83%94%e1%83%9d%e1%83%a0%e1%83%90%e1%83%93%e1%83%98/%e1%83%97%e1%83%ae%e1%83%98%e1%83%9a%e1%83%90%e1%83%9b%e1%83%a3%e1%83%a0%e1%83%98-%e1%83%9b%e1%83%94%e1%83%9d%e1%83%a0%e1%83%90%e1%83%93%e1%83%98/",
        "used",
    ),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

CSV_FILENAME = "snowmania_ski_table.csv"
SHOP_NAME = "snowmania.ge"

# ---------- НАСТРОЙКИ РЕЖИМА ОБХОДА ----------

TEST_MODE = False       # если True — ограничиваемся несколькими страницами
TEST_MAX_PAGES = 1     # сколько страниц на категорию в тесте


def get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def build_category_page_url(base_category_url: str, page: int) -> str:
    """
    WooCommerce обычно использует /page/N/.
    page = 1 -> базовый url без /page/1/
    """
    base = base_category_url.rstrip("/")
    if page <= 1:
        return base + "/"
    return f"{base}/page/{page}/"


def clean_price_value(p: str) -> str:
    """
    Оставляем только число в виде '1700.00':
    - убираем валюту, пробелы, разделители тысяч.
    """
    # сначала вытащим только число вида 1,700.00 или 1700.00
    match = re.search(r"[\d.,]+", p)
    if not match:
        return ""
    val = match.group(0)
    # убираем разделители тысяч
    val = val.replace(",", "").replace("\xa0", "").strip()
    return val


def parse_price_block(price_el) -> Tuple[Optional[str], Optional[str]]:
    """
    Возвращает (original, current) как строки с числом.
    original = исходная (перечёркнутая), current = текущая.

    Если есть только одна цена — кладём её в current, original = None.
    """
    if not price_el:
        return None, None

    # основной вариант — WooCommerce-цены
    amounts = price_el.select(".woocommerce-Price-amount bdi")

    if amounts:
        values = [clean_price_value(a.get_text(" ", strip=True)) for a in amounts]
        values = [v for v in values if v]  # убрать пустые
        if not values:
            return None, None
        if len(values) == 1:
            return None, values[0]
        else:
            return values[0], values[-1]

    # запасной вариант: обычный текст вроде:
    # "1,700.00 ₾ Original price was: 1,700.00 ₾. 1,150.00 ₾ Current price is: 1,150.00 ₾."
    text = price_el.get_text(" ", strip=True)
    nums = re.findall(r"[\d.,]+", text)
    nums = [clean_price_value(n) for n in nums if clean_price_value(n)]
    if not nums:
        return None, None
    if len(nums) == 1:
        return None, nums[0]
    return nums[0], nums[-1]


def extract_products_from_category_page(
    soup: BeautifulSoup,
) -> List[Tuple[str, str]]:
    """
    Возвращает список кортежей:
    (product_url, title)

    На сайте нет ul.products li.product,
    берём все ссылки внутри h2/h3, у которых href содержит '/product/'.
    """
    products: List[Tuple[str, str]] = []
    seen_urls = set()

    for a in soup.select("h2 a, h3 a"):
        href = a.get("href")
        if not href:
            continue
        if "/product/" not in href:
            continue

        url = urljoin(BASE_DOMAIN, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        title = a.get_text(strip=True)
        products.append((url, title))

    return products


def get_product_categories(soup: BeautifulSoup) -> List[str]:
    """
    Достаём список категорий из блока 'კატეგორია: ...'
    (обычно .product_meta .posted_in a).
    """
    categories: List[str] = []

    meta = soup.select_one(".product_meta")
    if meta:
        for a in meta.select(".posted_in a"):
            txt = a.get_text(strip=True)
            if txt:
                categories.append(txt)

    # фоллбек: поиск по тексту "კატეგორია"
    if not categories:
        for span in soup.find_all("span"):
            if "კატეგორია" in span.get_text():
                for a in span.find_all("a"):
                    txt = a.get_text(strip=True)
                    if txt:
                        categories.append(txt)
                break

    return categories


def is_ski_product(soup: BeautifulSoup) -> bool:
    """
    Оставляем только САМИ ЛЫЖИ.
    Условие: среди категорий есть отдельный элемент 'თხილამური'.
    """
    cats = [c.strip().lower() for c in get_product_categories(soup)]
    return "თხილამური" in cats


def parse_product_page(url: str) -> Optional[Dict[str, Optional[str]]]:
    """
    Парсим детальную страницу товара.
    Если это не лыжи (нет категории 'თხილამური') — возвращаем None.
    """
    soup = get_soup(url)

    # ФИЛЬТР: только лыжи
    if not is_ski_product(soup):
        print(f"[SKIP] Not ski product (categories): {url}")
        return None

    # Заголовок товара
    title_el = soup.select_one("h1.product_title") or soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else ""

    # Блок цены
    price_el = soup.select_one("p.price, span.price, div.price")
    original, current = parse_price_block(price_el)

    # Доп. инфо (таблица атрибутов)
    brand = None
    sizes = None

    attrs_table = soup.select_one("table.woocommerce-product-attributes")
    if attrs_table:
        for row in attrs_table.select("tr"):
            th = row.find("th")
            td = row.find("td")
            if not th or not td:
                continue

            label = th.get_text(strip=True)
            value = td.get_text(" ", strip=True)

            if "ზომა" in label:      # размер
                sizes = value
            elif "ბრენდი" in label:  # бренд
                brand = value

    return {
        "model": title or None,
        "brand": brand,
        "sizes": sizes,        # строка с размерами, позже разнесём
        "original": original,  # исходная цена
        "current": current,    # текущая цена
    }


def split_sizes_to_list(sizes_raw: Optional[str]) -> List[Optional[str]]:
    """
    Превращает строку с размерами в список:
    "170, 177, 184" -> ["170", "177", "184"]
    Если размеров нет — возвращаем [None], чтобы была хотя бы одна строка.
    """
    if not sizes_raw:
        return [None]

    # вытащим все числа (на случай "170 სმ")
    nums = re.findall(r"\d+", sizes_raw)
    if not nums:
        return [sizes_raw.strip()] if sizes_raw.strip() else [None]
    return nums


def iter_category_products(base_category_url: str, condition: str):
    """
    Итерируем по страницам категории, пока есть товары.
    Для каждого товара:
    - берём ссылку с листинга (h2/h3 a[href*='/product/'])
    - открываем карточку
    - если это лыжи (категория 'თხილამური') — отдаём строки
      (по одной строке на каждый размер).
    """
    page = 1
    while True:
        if TEST_MODE and page > TEST_MAX_PAGES:
            break

        url = build_category_page_url(base_category_url, page)
        print(f"[INFO] Category={condition} page={page} url={url}")

        # --- ИСПРАВЛЕНИЕ: не падаем на 404, а прекращаем категорию ---
        try:
            soup = get_soup(url)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            print(
                f"[INFO] Stop category '{condition}' on page={page}: "
                f"HTTP {status} for url={url}"
            )
            # как только упёрлись в 404 (или другой HTTP-ошибке) —
            # прекращаем эту категорию и переходим к следующей
            break
        except Exception as e:
            print(f"[WARN] Failed to load category page {url}: {e}")
            # на всякий случай тоже выходим из категории
            break
        # -------------------------------------------------------------

        products = extract_products_from_category_page(soup)
        print(f"[INFO] Found {len(products)} products on page {page}")

        if not products:
            # страниц больше нет
            break

        for product_url, title in products:
            try:
                details = parse_product_page(product_url)
                # если не лыжи — parse_product_page вернёт None
                if details is None:
                    continue
            except Exception as e:
                print(f"[WARN] Failed to parse product page {product_url}: {e}")
                continue

            sizes_list = split_sizes_to_list(details["sizes"])

            for size in sizes_list:
                row = {
                    "shop": SHOP_NAME,
                    "condition": condition,  # new / used (из пути)
                    "brand": details["brand"],
                    "model": details["model"],
                    "size": size,
                    "original": details["original"],
                    "current": details["current"],
                    "url": product_url,
                }
                yield row

        page += 1
        time.sleep(1.0)


def main():
    fieldnames = [
        "shop",
        "condition",  # new / used
        "brand",
        "model",
        "size",       # один размер на строку
        "original",   # исходная цена (число)
        "current",    # текущая цена (число)
        "url",
    ]

    with open(CSV_FILENAME, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for base_url, condition in CATEGORY_URLS:
            for row in iter_category_products(base_url, condition):
                writer.writerow(row)


if __name__ == "__main__":
    main()

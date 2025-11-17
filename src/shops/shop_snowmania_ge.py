# shop_snowmania_ge.py
import re
from typing import Dict, List, Optional, Tuple, Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.parsing_ski.models import Product, MIN_SKI_LENGTH_CM, MAX_SKI_LENGTH_CM

BASE_DOMAIN = "https://snowmania.ge"

# Парсим только эти две категории (новые и б/у ЛЫЖИ)
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

SHOP_NAME = "snowmania.ge"

PRICE_NUMBER_RE = re.compile(r'[\d.,]+')

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
    match = re.search(r"[\d.,]+", p)
    if not match:
        return ""
    val = match.group(0)
    val = val.replace(",", "").replace("\xa0", "").strip()
    return val


def parse_price_block(text: str) -> tuple[float | None, float | None]:
    """
    Разбирает текстовый блок цены WooCommerce и возвращает (orig_price, price)
    в лари, как float.

    Пытаемся в первую очередь вытащить значения из явных фраз:
      - "Original price was: X"
      - "Current price is: Y"

    Фоллбек — берём все числа и выбираем адекватную пару.
    """
    if not text:
        return None, None

    # Нормализуем пробелы и кривые "₾.1,855.00"
    text = (
        text.replace("\xa0", " ")
            .replace("₾.", "₾ ")
    )

    def _to_float(s: str) -> Optional[float]:
        s = s.strip()
        if not s:
            return None
        s = s.replace(",", "")  # убираем разделитель тысяч
        try:
            return float(s)
        except ValueError:
            return None

    # 1) Пытаемся вытащить по фразам "Original price was" / "Current price is"
    orig_match = re.search(r"Original price was:\s*([\d.,]+)", text)
    curr_match = re.search(r"Current price is:\s*([\d.,]+)", text)

    if orig_match:
        orig = _to_float(orig_match.group(1))
    else:
        orig = None

    if curr_match:
        curr = _to_float(curr_match.group(1))
    else:
        curr = None

    # Если нашли обе — этого достаточно
    if orig is not None and curr is not None:
        return orig, curr

    # 2) Фоллбек: собираем все числа
    raw_numbers = PRICE_NUMBER_RE.findall(text)
    numbers: list[float] = []
    for raw in raw_numbers:
        v = _to_float(raw)
        if v is None:
            continue
        if v not in numbers:
            numbers.append(v)

    if not numbers:
        return None, None

    # Если есть "Original price was", но нет Current,
    # считаем: первая или максимальная — старая, последняя — текущая.
    if "Original price was" in text and len(numbers) >= 2:
        orig = max(numbers)
        curr = min(numbers)
        return orig, curr

    # Обычный случай – одна цена
    if len(numbers) == 1:
        return numbers[0], numbers[0]

    # Запасной вариант: несколько чисел без явных подсказок:
    # максимум – оригинальная, минимум – текущая
    orig = max(numbers)
    curr = min(numbers)
    return orig, curr


def extract_products_from_category_page(
    soup: BeautifulSoup,
) -> List[Tuple[str, str]]:
    """
    Возвращает список (url, title) для товаров с категории.

    На сайте snowmania.ge НЕТ стандартной разметки
    ul.products li.product, поэтому берём ссылки из заголовков h2/h3,
    у которых href содержит '/product/'.
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
    Условие: среди категорий есть подстрока 'თხილამური'.
    """
    cats = [c.strip().lower() for c in get_product_categories(soup)]
    return any("თხილამური" in c for c in cats)

def _price_to_float(value) -> Optional[float]:
    """
    Принимает float | int | str | None и возвращает float или None.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    s = clean_price_value(str(value))
    if not s:
        return None

    try:
        return float(s)
    except ValueError:
        return None

def _extract_price_from_element(el) -> Optional[float]:
    if not el:
        return None
    txt = el.get_text(" ", strip=True)
    return _price_to_float(txt)

def extract_prices_from_dom(soup: BeautifulSoup) -> tuple[float | None, float | None]:
    """
    Пытается достать цены прямо из DOM WooCommerce:
      <p class="price">
        <del>... 3,400.00 ...</del>
        <ins>... 1,700.00 ...</ins>
      </p>

    Если скидки нет (нет <ins>), берёт единственную сумму.
    """
    price_container = soup.select_one("p.price")
    if not price_container:
        return None, None

    # старое значение (перечёркнутая цена)
    del_amount = price_container.select_one("del .woocommerce-Price-amount, del span.woocommerce-Price-amount")
    # новое значение (актуальная цена)
    ins_amount = price_container.select_one("ins .woocommerce-Price-amount, ins span.woocommerce-Price-amount")

    orig = _extract_price_from_element(del_amount) if del_amount else None
    curr = _extract_price_from_element(ins_amount) if ins_amount else None

    # Есть и старая, и новая – отлично
    if orig is not None and curr is not None:
        return orig, curr

    # Нет скидки: ищем любую сумму в p.price
    if orig is None and curr is None:
        amount = price_container.select_one(".woocommerce-Price-amount, span.woocommerce-Price-amount")
        v = _extract_price_from_element(amount) if amount else None
        return v, v

    # Если нашли только одну из цен – пусть обе будут одинаковыми
    if curr is None and orig is not None:
        curr = orig
    if orig is None and curr is not None:
        orig = curr

    return orig, curr

def parse_product_page(url: str) -> Optional[Dict[str, Optional[str]]]:
    """
    Парсит:
      - бренд (если есть)
      - модель (используем заголовок товара)
      - размеры (строкой)
      - цены (original/current)
    Если товар не является лыжами — возвращаем None.
    """
    try:
        soup = get_soup(url)
    except Exception as e:
        print(f"[WARN] Failed to load product page {url}: {e}")
        return None

    if not is_ski_product(soup):
        return None

    # заголовок — как модель
    title_el = (
        soup.select_one("h1.product_title")
        or soup.select_one(".product_title")
        or soup.find("h1")
    )
    title = title_el.get_text(" ", strip=True) if title_el else None

    # таблица характеристик: ищем бренд и размеры
    brand = None
    sizes = None

    attrs_table = soup.select_one("table.woocommerce-product-attributes")
    if attrs_table:
        for tr in attrs_table.select("tr"):
            th = tr.select_one("th")
            td = tr.select_one("td")
            if not th or not td:
                continue
            label = th.get_text(" ", strip=True)
            value = td.get_text(" ", strip=True)
            if not value:
                continue

            label_lower = label.lower()
            if "ზომა" in label_lower:
                sizes = value
            elif "ბრენდი" in label_lower:
                brand = value

    # 1) пробуем достать цены из DOM
    original, current = extract_prices_from_dom(soup)

    # 2) если не получилось — фоллбек через текстовый разбор
    if original is None or current is None:
        price_wrapper = soup.select_one("p.price, span.price, div.price")
        price_text = price_wrapper.get_text(" ", strip=True) if price_wrapper else ""
        original, current = parse_price_block(price_text)

    # опционально на время отладки:
    # print(f"[DBG] {url} -> original={original}, current={current}")

    return {
        "model": title or None,
        "brand": brand,
        "sizes": sizes,
        "original": original,
        "current": current,
    }

def split_sizes_to_list(sizes_raw: Optional[str]) -> List[Optional[str]]:
    """
    Превращает строку с размерами в список:
    "170, 177, 184" -> ["170", "177", "184"]
    Если размеров нет — возвращаем [None], чтобы была хотя бы одна строка.
    """
    if not sizes_raw:
        return [None]

    nums = re.findall(r"\d+", sizes_raw)
    if not nums:
        return [sizes_raw.strip()] if sizes_raw.strip() else [None]
    return nums


def size_str_to_length_cm(size: Optional[str]) -> Optional[int]:
    """
    Превращает строку с размером в число сантиметров.
    Примеры:
      "170" -> 170
      "170 cm" -> 170
      None / мусор -> None
    """
    if not size:
        return None

    m = re.search(r"\d+", str(size))
    if not m:
        return None

    try:
        return int(m.group(0))
    except ValueError:
        return None


def is_size_in_ski_range(size: Optional[str]) -> bool:
    """
    True, если длина в пределах MIN_SKI_LENGTH_CM..MAX_SKI_LENGTH_CM.
    Именно этим фильтром мы определяем "подходящие" лыжи.
    """
    length = size_str_to_length_cm(size)
    if length is None:
        return False
    return MIN_SKI_LENGTH_CM <= length <= MAX_SKI_LENGTH_CM

def iter_category_products(
    base_category_url: str,
    condition: str,
    *,
    test_mode: bool = False,
    test_max_pages: int = 1,
) -> Iterable[Dict[str, Optional[str]]]:
    """
    Итерируем по всем страницам категории:
      - открываем список
      - идём на карточки товаров
      - берём ТОЛЬКО лыжи подходящей длины (по MIN_SKI_LENGTH_CM..MAX_SKI_LENGTH_CM),
        и на выход отдаём по одной строке на каждый подходящий размер.
    """
    page = 1
    while True:
        if test_mode and page > test_max_pages:
            break

        url = build_category_page_url(base_category_url, page)
        print(f"[INFO] Category={condition} page={page} url={url}")

        # не падаем на 404, а прекращаем категорию
        try:
            soup = get_soup(url)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            print(
                f"[INFO] Stop category '{condition}' on page={page}: "
                f"HTTP {status} for url={url}"
            )
            break
        except Exception as e:
            print(
                f"[WARN] Failed to load category '{condition}' page={page} url={url}: {e}"
            )
            break

        products = extract_products_from_category_page(soup)
        print(f"[INFO] Found {len(products)} products on page {page}")

        if not products:
            break

        for product_url, _title in products:
            try:
                details = parse_product_page(product_url)
                # Если не удалось распарсить или это не лыжи — пропускаем
                if details is None:
                    continue
            except Exception as e:
                print(f"[WARN] Failed to parse product page {product_url}: {e}")
                continue

            # sizes_raw — строка "170, 177, 184"
            sizes_list = split_sizes_to_list(details["sizes"])

            # Перебираем размеры и оставляем только подходящие по длине
            for size in sizes_list:
                if not is_size_in_ski_range(size):
                    continue

                yield {
                    "shop": SHOP_NAME,
                    "condition": condition,  # "new" / "used"
                    "brand": details["brand"],
                    "model": details["model"],
                    "size": size,
                    "original": details["original"],
                    "current": details["current"],
                    "url": product_url,
                }

        page += 1


def scrape_snowmania(
    test_mode: bool = False,
    test_max_pages: int = 1,
) -> List[Product]:
    """
    Основная функция: обходит snowmania.ge (новые + б/у лыжи)
    и возвращает список Product.
    """
    print(f"[INFO] Start scraping {SHOP_NAME}")
    products: List[Product] = []

    for base_url, condition in CATEGORY_URLS:
        print(f"[INFO] Category '{condition}'")
        for row in iter_category_products(
            base_url,
            condition,
            test_mode=test_mode,
            test_max_pages=test_max_pages,
        ):
            current_price = _price_to_float(row["current"])
            old_price = _price_to_float(row["original"])

            size = row["size"]
            sizes_list = [size] if size else []

            p = Product(
                shop=SHOP_NAME,
                url=row["url"],
                brand=row["brand"],
                model=row["model"],
                title=row["model"],
                sizes=sizes_list,
                current_price=current_price,
                old_price=old_price,
                currency="GEL",
                in_stock=True,
                quantity=None,
                shop_sku=None,
                condition=condition,  # "new" / "used"
            )
            products.append(p)

    print(f"[OK] Finished {SHOP_NAME}, total rows: {len(products)}")
    return products


if __name__ == "__main__":
    # standalone debug
    res = scrape_snowmania(test_mode=True, test_max_pages=1)
    print(f"Scraped {len(res)} rows from {SHOP_NAME}")

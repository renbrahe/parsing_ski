# shop_burosports_ge.py
import time
import re
from typing import List, Optional, Tuple, Dict
from urllib.parse import urljoin
from src.parsing_ski.models import Product, MIN_SKI_LENGTH_CM, MAX_SKI_LENGTH_CM

import requests
from bs4 import BeautifulSoup


BASE_DOMAIN = "https://burusports.ge"

# Категория лыж (английская версия)
CATEGORY_URL = f"{BASE_DOMAIN}/en/products/tkhilamuri/tkhilamuri"

# Небольшой список брендов для попытки автоопределения по <title>
KNOWN_BRANDS = [
    "Rossignol",
    "Head",
    "Atomic",
    "Fischer",
    "Salomon",
    "Scott",
    "Volkl",
    "Völkl",
    "Voelkl",
    "Blizzard",
    "Nordica",
    "Elan",
    "K2",
    "Dynastar",
    "Armada",
]

# Фильтры по брендам (английская версия каталога)
BRAND_FILTER_URLS: Dict[str, str] = {
    "Rossignol": "https://burusports.ge/en/products/tkhilamuri/tkhilamuri?keyword=&sort=&discount=&brand%5B%5D=14",
    "Volkl":     "https://burusports.ge/en/products/tkhilamuri/tkhilamuri?keyword=&sort=&discount=&brand%5B%5D=16",
    "Scott":     "https://burusports.ge/en/products/tkhilamuri/tkhilamuri?keyword=&sort=&discount=&brand%5B%5D=7",
}

# сюда сложим соответствия "нормализованное название модели" -> "бренд"
BRAND_BY_MODEL: Dict[str, str] = {}


def _get_soup(url: str) -> BeautifulSoup:
    """Загружает страницу и возвращает BeautifulSoup."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def _normalize_model_name(name: str) -> str:
    """
    Нормализуем название модели:
    - trim
    - схлопываем лишние пробелы
    - lower()
    """
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def _build_brand_model_map() -> None:
    """
    Один раз обходит страницы с фильтрами брендов
    и заполняет BRAND_BY_MODEL.
    """
    global BRAND_BY_MODEL
    if BRAND_BY_MODEL:
        return  # уже построили

    mapping: Dict[str, str] = {}

    for brand, base_url in BRAND_FILTER_URLS.items():
        page = 1
        while True:
            if page == 1:
                url = base_url
            else:
                # пагинация у них через ?page=2, ?page=3 и т.п.
                url = f"{base_url}&page={page}"

            try:
                soup = _get_soup(url)
            except Exception as e:
                print(f"[WARN] Failed to load brand page {url}: {e}")
                break

            card_links = soup.select("a.product-list-item")
            if not card_links:
                break  # товаров нет -> дальше страниц нет

            for a in card_links:
                full_text = a.get_text(" ", strip=True)

                # Разбиваем на токены
                tokens = full_text.split()

                # Убираем с конца максимум два "ценовых" токена (3–4 цифры)
                prices_removed = 0
                while tokens and prices_removed < 2 and re.fullmatch(r"\d{3,4}", tokens[-1]):
                    tokens.pop()
                    prices_removed += 1

                model_name = " ".join(tokens).strip()

                key = _normalize_model_name(model_name)
                if key and key not in mapping:
                    mapping[key] = brand

            page += 1
            time.sleep(0.2)

    BRAND_BY_MODEL = mapping
    print(f"[INFO] burusports: brand-model map built, {len(BRAND_BY_MODEL)} entries")


def _detect_brand(page_title: str) -> Optional[str]:
    """Пытаемся определить бренд по <title> страницы."""
    title_lower = (page_title or "").lower()
    for b in KNOWN_BRANDS:
        if b.lower() in title_lower:
            return b
    return None


def _extract_prices_from_list_text(text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    На листинговой странице один <a class="product-list-item"> выглядит примерно так:
        'Escaper 97 Nano 2800 1600'
        'SUPER VIRAGE VI TECH KONECT 2800'
        'Blaze 94 Grey/Red 2100'
        'SCO Ski Superguide Freetour 2250 1350'

    Берём ВСЕ числа из текста:
      - если одно число: старая = текущая
      - если два и более: считаем, что [0] = старая, [1] = текущая.
    """
    if not text:
        return None, None

    nums = [m.group(0) for m in re.finditer(r"\d{3,4}", text)]
    if not nums:
        return None, None

    def to_float(s: str) -> float:
        return float(s.replace(",", ".").replace("\xa0", " "))

    if len(nums) == 1:
        v = to_float(nums[0])
        return v, v
    else:
        old_price = to_float(nums[0])
        current_price = to_float(nums[1])
        return old_price, current_price

def _extract_sizes_from_product_text(soup: BeautifulSoup) -> List[str]:
    """
    Ищем блок 'Size:' ... 'Adult:' / 'Quantity:' и забираем оттуда все длины.

    Работает и с записью типа '165სმ' (см по-грузински).
    """
    text = soup.get_text("\n", strip=True)

    if "Size:" not in text:
        return []

    # Берём всё после первого 'Size:'
    part = text.split("Size:", 1)[1]

    # Обрезаем по первому встреченному "стоп-слову"
    for stop in ("Adult:", "Quantity:", "Add to cart", "Similar products"):
        if stop in part:
            part = part.split(stop, 1)[0]

    # Убираем всё, что не цифра и не пробел → '165სმ' превратится в '165 '
    part_clean = re.sub(r"[^\d\s]", " ", part)

    sizes: List[str] = []
    for m in re.finditer(r"(\d{2,3})", part_clean):
        value = m.group(1)
        if value not in sizes:
            sizes.append(value)

    return sizes


def _parse_product_page(
    url: str,
    list_old_price: Optional[float],
    list_current_price: Optional[float],
) -> Optional[Product]:
    """
    Парсим страницу конкретного товара.

    ЦЕНЫ мы сюда уже передаём с листинговой страницы (list_old_price, list_current_price).

    Из карточки товара вытаскиваем:
    - model: из <h1.main-title>
    - brand: пытаемся определить по <title>
    - sizes: все ссылки в блоке размеров (div.group a), например '165სმ', '160სმ' и т.п.
    """
    try:
        soup = _get_soup(url)
    except Exception as e:
        print(f"[WARN] Failed to load product page {url}: {e}")
        return None

    # Название модели
    h1 = soup.select_one("h1.main-title")
    if not h1:
        print(f"[WARN] No <h1> found on product page {url}")
        return None
    model = h1.get_text(strip=True)

    # Бренд по <title>
    # Сначала пытаемся определить бренд по словарю "модель -> бренд"
    normalized_model = _normalize_model_name(model)
    brand = BRAND_BY_MODEL.get(normalized_model)

    # Если в словаре нет — пробуем по <title>
    if not brand:
        page_title = soup.title.string if soup.title else ""
        brand = _detect_brand(page_title)

    # Размеры (Size) – просто собираем все ссылки в блоке размеров
    sizes = _extract_sizes_from_product_text(soup)

    # Цены берём только с листинга
    old_price = list_old_price
    current_price = list_current_price or list_old_price

    if current_price is None and old_price is None:
        print(f"[WARN] No price info for product {url} (from list page)")
        # Можно вернуть None, но лучше всё же создать Product без цены,
        # чтобы не терять запись. Здесь оставляем как есть и создаём.
        # return None

    product = Product(
        shop="burusports",
        url=url,
        brand=brand,
        model=model,
        sizes=sizes,
        current_price=current_price,
        old_price=old_price,
        condition="new",
    )
    return product

def product_to_unified_rows(p: Product) -> List[dict]:
    rows: List[dict] = []

    sizes = getattr(p, "sizes", []) or []

    # парсим длины из p.sizes, например "185", "185სმ", "176 см"
    lengths: List[int] = []
    for s in sizes:
        # оставляем только цифры и пробелы
        clean = re.sub(r"[^\d\s]", " ", s or "")
        for m in re.finditer(r"(\d{2,3})", clean):
            L = int(m.group(1))
            if MIN_SKI_LENGTH_CM <= L <= MAX_SKI_LENGTH_CM and L not in lengths:
                lengths.append(L)

    # если удалось достать длины из sizes — делаем по строке на каждую длину
    if lengths:
        for L in lengths:
            rows.append(
                {
                    "shops": p.shop,
                    "brand": p.brand,
                    "model": p.model,
                    "condition": p.condition,
                    "orig_price": p.old_price,
                    "price": p.current_price,
                    "length_cm": L,
                    "url": p.url,
                }
            )
        return rows

    # fallback, если sizes пустой — пробуем выдернуть длину из model
    m = re.search(r"(\d{3})", p.model or "")
    L = None
    if m:
        L = int(m.group(1))
        if not (MIN_SKI_LENGTH_CM <= L <= MAX_SKI_LENGTH_CM):
            L = None

    rows.append(
        {
            "shops": p.shop,
            "brand": p.brand,
            "model": p.model,
            "condition": p.condition,
            "orig_price": p.old_price,
            "price": p.current_price,
            "length_cm": L,
            "url": p.url,
        }
    )

    return rows


def scrape_burosports(test_mode: bool = False) -> List[Product]:
    """
    Основная точка входа.

    - test_mode=True: парсим только первую страницу каталога.
    - Иначе идём по страницам ?page=2, ?page=3,... пока не кончатся товары.

    ВАЖНО: цены парсим ТОЛЬКО с листинговых страниц, чтобы не ловить мусор
    из блока "Similar products" на карточках товара.
    """
    print("[INFO] Start scraping burusports.ge")
    _build_brand_model_map()

    products: List[Product] = []
    page = 1

    while True:
        if page == 1:
            url = CATEGORY_URL
        else:
            url = f"{CATEGORY_URL}?page={page}"

        print(f"[INFO] burusports page={page} url={url}")

        try:
            soup = _get_soup(url)
        except Exception as e:
            print(f"[WARN] Failed to load category page {url}: {e}")
            break

        # Карточки товаров на странице (каждая содержит название и 1–2 числа цен)
        card_links = soup.select("a.product-list-item")
        if not card_links:
            # Пустая страница -> достигли конца
            print(f"[INFO] No products found on page {page}, stopping.")
            break

        for a in card_links:
            href = a.get("href")
            if not href:
                continue
            product_url = urljoin(BASE_DOMAIN, href)

            # Текст карточки: 'Escaper 97 Nano 2800 1600'
            text = a.get_text(" ", strip=True)
            list_old_price, list_current_price = _extract_prices_from_list_text(text)

            try:
                product = _parse_product_page(
                    product_url,
                    list_old_price=list_old_price,
                    list_current_price=list_current_price,
                )
                if product:
                    products.append(product)
            except Exception as e:
                print(f"[WARN] Failed to parse product {product_url}: {e}")

            # Небольшая пауза, чтобы не долбить сайт
            time.sleep(0.3)

        if test_mode:
            # В тестовом режиме только первая страница
            print("[INFO] Test mode is ON, stopping after first page.")
            break

        page += 1
        # небольшая пауза между страницами
        time.sleep(0.5)

    print(f"[INFO] burusports: {len(products)} products scraped")
    return products


if __name__ == "__main__":
    # Небольшой самотест
    items = scrape_burosports(test_mode=True)
    print(f"Scraped {len(items)} products (test mode)")

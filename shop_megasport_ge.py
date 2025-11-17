# shop_megasport_ge.py
import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from models import Product, MIN_SKI_LENGTH_CM, MAX_SKI_LENGTH_CM

logger = logging.getLogger(__name__)

BASE = "https://megasport.ge"
CATEGORY_URL = f"{BASE}/category/skiing"

PRICE_RE = re.compile(r"([\d.,]+)\s*₾")
SIZE_RE = re.compile(r"\b(\d{3})\b")  # 3-значные длины типа 160, 174 и т.п.


# ---------- Вспомогательные функции ----------

def _extract_product_links_from_html(html: str) -> List[str]:
    """
    Находит все ссылки на товары вида /products/...
    """
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/products/" not in href:
            continue
        full = urljoin(BASE, href)
        links.append(full)

    uniq = sorted(set(links))
    logger.info(f"megasport: found {len(uniq)} product links on category page")
    return uniq


def _to_float(s: str) -> Optional[float]:
    s = s.strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_product_html(html: str, url: str) -> Optional[Product]:
    """
    Парсит HTML одной карточки товара и возвращает Product.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # ---- название ----
    h2 = soup.find("h2", class_=lambda c: c and "text-heading" in c)
    name = h2.get_text(strip=True) if h2 else None
    if not name:
        logger.warning(f"megasport: no name on {url}")
        return None

    # бренд / модель
    parts = name.split()
    brand = parts[0] if parts else None
    model = " ".join(parts[1:]) if len(parts) > 1 else None

    # ---- цена / старая цена ----
    price_matches = PRICE_RE.findall(text)
    current_price: Optional[float] = None
    old_price: Optional[float] = None

    if price_matches:
        nums = [n for n in (_to_float(x) for x in price_matches) if n is not None]
        if len(nums) >= 2 and nums[1] < nums[0]:
            old_price, current_price = nums[0], nums[1]
        elif nums:
            current_price = nums[-1]

    if current_price is None:
        logger.warning(f"megasport: no price on {url}")
        return None

    # ---- длины (выбираем лыжи) ----
    sizes: List[int] = []

    ul = soup.find("ul", class_=lambda c: c and "colors" in c)
    if ul:
        for li in ul.find_all("li"):
            t = li.get_text(strip=True)
            m = SIZE_RE.search(t)
            if not m:
                continue
            length = int(m.group(1))
            if not (MIN_SKI_LENGTH_CM <= length <= MAX_SKI_LENGTH_CM):
                continue
            if length not in sizes:
                sizes.append(length)

    # если вообще нет подходящих длин — считаем, что это не лыжи (ботинки/шлем и т.п.)
    if not sizes:
        logger.info(f"megasport: skip non-ski product {url} (no ski lengths found)")
        return None

    sizes.sort()
    sizes_str = [str(s) for s in sizes]

    return Product(
        shop="megasport",
        url=url,
        brand=brand,
        model=model,
        title=name,
        sizes=sizes_str,
        current_price=current_price,
        old_price=old_price,
        currency="GEL",
        condition="new",
    )


# ---------- Основной раннер ----------

def scrape_megasport(test_mode: bool = False) -> List[Product]:
    """
    Скрейпер Megasport с эмуляцией браузера:

    1. Открывает /category/skiing в Chromium через Playwright.
    2. Жмёт кнопку "Load More" пока она есть (или 1 раз в test_mode).
    3. Собирает все ссылки /products/...
    4. По каждой ссылке открывает карточку и парсит товар.
    5. Возвращает только те товары, где найдены "лыжные" длины.
    """
    logger.info(f"Start scraping megasport.ge (test_mode={test_mode})")

    items: List[Product] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Заходим в категорию SKIING
        page.goto(CATEGORY_URL, wait_until="networkidle")

        # 2. Жмём Load More
        max_clicks = 1 if test_mode else 20
        for _ in range(max_clicks):
            btn = page.query_selector('button:has-text("Load More")')
            if not btn or not btn.is_enabled():
                break
            logger.info("megasport: click Load More")
            btn.click()
            # даём странице дорисоваться
            page.wait_for_timeout(1500)

        # 3. Собираем ссылки на товары
        category_html = page.content()
        product_links = _extract_product_links_from_html(category_html)

        if test_mode:
            product_links = product_links[:10]
            logger.info(f"megasport: test_mode, limit to {len(product_links)} products")

        # 4. Парсим каждую карточку
        for url in product_links:
            logger.info(f"megasport: parse product {url}")
            page.goto(url, wait_until="networkidle")
            html = page.content()
            prod = _parse_product_html(html, url)
            if prod:
                items.append(prod)

        browser.close()

    logger.info(f"megasport: {len(items)} ski products scraped")
    return items

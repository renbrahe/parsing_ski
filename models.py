# models.py
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Product:
    shop: str
    url: str

    brand: Optional[str] = None
    model: Optional[str] = None
    title: Optional[str] = None

    sizes: List[str] = None          # список строк, потом склеим в БД
    current_price: Optional[float] = None
    old_price: Optional[float] = None
    currency: Optional[str] = "GEL"
    in_stock: bool = True
    quantity: Optional[int] = None   # сколько пар в магазине (если есть инфа)
    shop_sku: Optional[str] = None

    def sizes_as_str(self) -> str:
        return ", ".join(self.sizes) if self.sizes else ""


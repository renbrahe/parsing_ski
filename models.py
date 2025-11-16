# models.py
from dataclasses import dataclass, field
from typing import List, Optional

# Глобальные параметры фильтра длины лыж (в сантиметрах)
# Используются, чтобы отфильтровать "подходящие" лыжи на разных магазинах.
MIN_SKI_LENGTH_CM: int = 90
MAX_SKI_LENGTH_CM: int = 210


@dataclass
class Product:
    shop: str
    url: str

    brand: Optional[str] = None
    model: Optional[str] = None
    title: Optional[str] = None

    # list of sizes, we will join it later if needed
    sizes: List[str] = field(default_factory=list)

    current_price: Optional[float] = None
    old_price: Optional[float] = None
    currency: Optional[str] = "GEL"
    in_stock: bool = True
    quantity: Optional[int] = None
    shop_sku: Optional[str] = None

    # "new" / "used"
    condition: Optional[str] = None

    def sizes_as_str(self) -> str:
        return ", ".join(self.sizes) if self.sizes else ""

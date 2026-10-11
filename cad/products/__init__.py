"""The two products: Hologram Cam (camera glasses) and Hologram VR (helmet headset)."""
from __future__ import annotations

from ..product import Product
from .cam import PRODUCT as CAM
from .vr import PRODUCT as VR

PRODUCTS: tuple[Product, ...] = (CAM, VR)
BY_KEY: dict[str, Product] = {p.key: p for p in PRODUCTS}

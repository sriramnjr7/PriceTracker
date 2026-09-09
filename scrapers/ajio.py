"""Ajio scraper (JS-rendered).

Ajio is a fully client-side (React) app: price and title only appear after
hydration, hence ``prefer_js=True``.  Key markup:

* title  -- ``<h1 class="product-name">`` (fallback ``.prod-name``)
* selling price -- ``<span class="prod-sp">``
* MRP    -- ``.prod-mrp`` (strikethrough; excluded so we alert on the real
  selling price and correctly handle deal/discount badges)
"""

from __future__ import annotations

from .base import BaseScraper


class AjioScraper(BaseScraper):
    platform = "ajio"
    prefer_js = True

    title_selectors = (
        "h1[class*='product-name']",
        ".prod-name",
        "h1[class*='name']",
    )

    price_selectors = (
        ".prod-sp",
        ".price-2",
        "[class*='price']",
    )

    out_of_stock_keywords = (
        "out of stock",
        "sold out",
        "currently unavailable",
        "not available",
    )
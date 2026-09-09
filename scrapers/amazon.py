"""Amazon India scraper with deal hunting & coupon glitch extraction.

Supports single product tracking, coupon detection (e.g. Save ₹2,000 with coupon),
and automated deal/clearance searches.
"""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
import httpx

from .base import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)


class AmazonScraper(BaseScraper):
    platform = "amazon"
    prefer_js = False

    title_selectors = (
        "#productTitle",
        "span#productTitle",
    )

    price_selectors: tuple[str, ...] = (
        ".a-price.priceToPay .a-offscreen",
        ".a-price.apex-pricetopay-value .a-offscreen",
        "#corePrice_feature_div .apex-pricetopay-value .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
        "#priceblock_dealprice",
        "#priceblock_ourprice",
    )

    main_price_containers: tuple[str, ...] = (
        "#corePriceDisplay_desktop_feature_div",
        "#corePrice_feature_div",
        "#apex_desktop",
        "#corePriceDisplay_mobile_feature_div",
        "#apex_mobile",
        "#priceInsideBuyBox_feature_div",
        "#desktop_buybox",
        "#mobile_buybox",
        "#priceblock_dealprice",
        "#priceblock_ourprice",
        "#priceblock_saleprice",
        "#tp_price_block_total_price_ww",
    )

    unwanted_subselectors: tuple[str, ...] = (
        "warranty",
        "protection",
        "insurance",
        "onsitego",
        "accessory",
        "accessories",
        "fbt",
        "sims",
        "carousel",
        "sponsored",
        "emi",
        "bundle",
        "tradein",
        "addon",
        "add-on",
        "attachment",
        "cart-protection",
        "checkbox",
        "a-text-price",
        "apex-basisprice-value",
        "apex-basis-price-value",
    )

    out_of_stock_keywords: tuple[str, ...] = (
        "currently unavailable",
        "temporarily out of stock",
        "out of stock",
        "we don't know when or if this item will be back in stock",
    )

    def _extract_price(self, soup: BeautifulSoup) -> Optional[float]:
        """Extract selling price strictly from the primary buybox, avoiding protection plans, warranties, and accessories."""
        # 1. Authoritative: Schema.org Product JSON-LD
        import json
        for script in soup.find_all("script"):
            stype = script.get("type", "")
            if "ld+json" in stype or "json" in stype:
                txt = script.string or script.get_text()
                if not txt or "offers" not in txt:
                    continue
                try:
                    data = json.loads(txt)
                    if isinstance(data, list) and data:
                        data = data[0]
                    if isinstance(data, dict):
                        offers = data.get("offers")
                        if isinstance(offers, dict) and "price" in offers:
                            val = float(offers["price"])
                            if val > 0:
                                return val
                        elif isinstance(offers, list) and offers:
                            for off in offers:
                                if isinstance(off, dict) and "price" in off:
                                    val = float(off["price"])
                                    if val > 0:
                                        return val
                except Exception:
                    continue

        # Helper to verify an element is not inside an unwanted add-on / warranty
        def is_clean_node(node) -> bool:
            curr = node
            depth = 0
            while curr and depth < 25:
                c_cls = " ".join(curr.get("class", [])) if isinstance(curr.get("class"), list) else str(curr.get("class") or "")
                c_id = str(curr.get("id") or "")
                combined = f"{c_cls} {c_id}".lower()
                if any(uw in combined for uw in self.unwanted_subselectors):
                    return False
                if curr.name == "body":
                    break
                curr = curr.parent
                depth += 1
            return True

        # 2. Main BuyBox & Core Price containers
        for container_sel in self.main_price_containers:
            container = soup.select_one(container_sel)
            if not container or not is_clean_node(container):
                continue

            for p_sel in (
                ".priceToPay .a-offscreen",
                ".apex-pricetopay-value .a-offscreen",
                ".priceToPay .a-price-whole",
                ".apex-pricetopay-value .a-price-whole",
                ".priceToPay",
                ".apex-pricetopay-value",
                "#priceblock_dealprice",
                "#priceblock_ourprice",
                "#priceblock_saleprice",
            ):
                for node in container.select(p_sel):
                    if not is_clean_node(node):
                        continue

                    val = self.clean_price(node.get_text(" ", strip=True))
                    if val is not None and val > 0:
                        return val

        # 3. Fallback to centerCol or dedicated priceToPay anywhere in page (e.g. minimal test snippets)
        for p_sel in (
            "#centerCol .priceToPay .a-offscreen",
            "#centerCol .apex-pricetopay-value .a-offscreen",
            ".priceToPay .a-offscreen",
            ".apex-pricetopay-value .a-offscreen",
            ".priceToPay .a-price-whole",
            ".priceToPay",
        ):
            for node in soup.select(p_sel):
                if not is_clean_node(node):
                    continue

                val = self.clean_price(node.get_text(" ", strip=True))
                if val is not None and val > 0:
                    return val

        return None

    def _extract_stock(self, soup: BeautifulSoup) -> bool:
        """Precise availability check via dedicated #availability node."""
        availability = soup.select_one("#availability span")
        if availability is not None:
            text = availability.get_text(" ", strip=True).lower()
            if "currently unavailable" in text or "out of stock" in text:
                return False
            if "in stock" in text:
                return True
        return super()._extract_stock(soup)

    def extract_coupon(self, card_or_soup: BeautifulSoup, base_price: float) -> tuple[float, Optional[str]]:
        """Detect Amazon coupon (e.g. Save ₹2,000 with coupon or 20% coupon)."""
        coupon_el = card_or_soup.select_one(
            "[class*='coupon'], .s-coupon-unclipped, label[id*='coupon'], #couponBadge, span.a-badge-text"
        )
        if not coupon_el:
            return 0.0, None

        coupon_text = coupon_el.get_text(" ", strip=True)
        if not coupon_text or "coupon" not in coupon_text.lower():
            return 0.0, None

        # 1. Check percent coupon first: e.g. "Save 20% with coupon" or "20% coupon"
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", coupon_text, re.IGNORECASE)
        if pct_match and base_price > 0:
            try:
                pct = float(pct_match.group(1))
                return round(base_price * (pct / 100.0), 2), coupon_text
            except ValueError:
                pass

        # 2. Check flat cash coupon: e.g. "Save ₹2,000" or "Save 500"
        cash_match = re.search(r"Save\s*(?:₹|Rs\.?|INR)?\s*([\d,]+)(?!\s*%)", coupon_text, re.IGNORECASE)
        if cash_match:
            try:
                discount_val = float(cash_match.group(1).replace(",", ""))
                return discount_val, coupon_text
            except ValueError:
                pass

        return 0.0, coupon_text

    async def scan_deals(
        self,
        query: str,
        min_discount: float = 50.0,
        max_price: Optional[float] = None,
        min_mrp: Optional[float] = None,
        negative_keywords: Optional[List[str]] = None,
        custom_url: Optional[str] = None,
        brand: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """Search Amazon India for deals matching brand facet, discount, price floor, and negative filters."""
        if custom_url:
            url = custom_url
        else:
            disc_tier = int(min_discount) if min_discount >= 10 else 10
            rh_parts = [f"p_8%3A{disc_tier}-"]
            if brand:
                rh_parts.append(f"p_89%3A{quote_plus(brand)}")
            rh_str = "%2C".join(rh_parts)
            url = f"https://www.amazon.in/s?k={quote_plus(query)}&rh={rh_str}"

        headers = {
            "User-Agent": self._random_user_agent(),
            "Accept-Language": "en-IN,en;q=0.9",
        }

        deals: List[dict[str, Any]] = []
        negative_set = [k.lower() for k in (negative_keywords or [])]

        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
                if r.status_code != 200:
                    return []

                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.select("div[data-component-type='s-search-result']")

                for card in cards:
                    h2 = card.select_one("h2")
                    if not h2:
                        continue
                    title = h2.get_text(" ", strip=True)
                    title_lower = title.lower()

                    # 1. Negative Keyword Filter (Rejects accessories/cases)
                    if any(neg in title_lower for neg in negative_set):
                        continue

                    # 2. Extract Link
                    link_el = card.select_one("h2 a, a.a-link-normal")
                    if not link_el or not link_el.get("href"):
                        continue
                    href = link_el["href"]
                    clean_url = "https://www.amazon.in" + href.split("?")[0] if href.startswith("/") else href.split("?")[0]

                    # 3. Extract ASIN (stable product identifier)
                    asin = card.get("data-asin", "")

                    # 4. Extract Explicit Brand from structured metadata
                    #    Amazon renders brand in a dedicated row below the title,
                    #    typically in spans with class patterns like:
                    #      - "a-size-base-plus a-color-base" (brand name)
                    #      - "a-size-base" in a row after the title
                    scraped_brand = None
                    # Strategy A: Look for the brand row (spans below h2, outside price)
                    brand_row = card.select_one("h2 + div .a-size-base-plus, h2 + div .a-size-base.a-color-base")
                    if brand_row:
                        brand_text = brand_row.get_text(strip=True)
                        if brand_text and len(brand_text) < 60 and not brand_text.startswith("₹"):
                            scraped_brand = brand_text

                    # Strategy B: Look for "by <Brand>" pattern in the card
                    if not scraped_brand:
                        for span in card.select("span.a-size-base"):
                            txt = span.get_text(strip=True)
                            if txt.lower().startswith("by ") and len(txt) < 60:
                                scraped_brand = txt[3:].strip()
                                break

                    # Strategy C: Check for "Visit the <Brand> Store" link
                    if not scraped_brand:
                        store_link = card.select_one("a[href*='/stores/'], a[href*='brandtextbin']")
                        if store_link:
                            store_text = store_link.get_text(strip=True)
                            # "Visit the Samsung Store" → "Samsung"
                            m = re.match(r"(?:Visit\s+the\s+)?(.+?)(?:\s+Store)?$", store_text, re.I)
                            if m and len(m.group(1)) < 50:
                                scraped_brand = m.group(1).strip()

                    # 5. Extract Selling Price
                    p_el = card.select_one(".a-price .a-offscreen")
                    if not p_el:
                        continue
                    price_val = self.clean_price(p_el.get_text(strip=True))
                    if price_val is None or price_val <= 0:
                        continue

                    # 6. Extract MRP
                    mrp_el = card.select_one(".a-price.a-text-price .a-offscreen")
                    mrp_val = self.clean_price(mrp_el.get_text(strip=True)) if mrp_el else price_val
                    mrp_val = mrp_val or price_val

                    # 7. Minimum MRP Sanity Filter
                    if min_mrp is not None and mrp_val < min_mrp:
                        continue

                    # 8. Extract Coupon & Compute Effective Price
                    coupon_val, coupon_text = self.extract_coupon(card, price_val)
                    effective_price = max(0.0, round(price_val - coupon_val, 2))

                    # 9. Calculate Effective Discount
                    if mrp_val > effective_price and mrp_val > 0:
                        discount_percent = round(((mrp_val - effective_price) / mrp_val) * 100.0, 1)
                    else:
                        discount_percent = 0.0

                    # 10. Filter by Thresholds
                    if discount_percent < min_discount and (max_price is None or effective_price > max_price):
                        continue

                    if max_price is not None and effective_price > max_price:
                        continue

                    deals.append({
                        "title": title,
                        "price": price_val,
                        "effective_price": effective_price,
                        "mrp": mrp_val,
                        "discount_percent": discount_percent,
                        "coupon_text": coupon_text,
                        "platform": "amazon",
                        "url": clean_url,
                        "in_stock": True,
                        "scraped_brand": scraped_brand,
                        "asin": asin,
                    })
        except Exception as exc:
            logger.warning("[amazon] deal scan error for query '%s': %s", query, exc)

        return deals
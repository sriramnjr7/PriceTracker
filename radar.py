"""Universal Steal Deal & Pricing Error Radar Engine.

Orchestrates multi-category sniper scans, master clearance feeds, coupon glitch
detection, negative keyword filtering, 24-hour de-duplication, and instant WhatsApp alerts.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, List, Optional

from brand_validator import BrandValidator, BrandStatus
from config import Settings, settings
from database import Database, get_database
from gemini_validator import GeminiDealValidator
from notifier import Notifier
from radar_rules import DEFAULT_RADAR_RULES, RadarRule
from scrapers import get_scraper

logger = logging.getLogger("radar")


class StealRadar:
    """Autonomous Universal Deal & Pricing Error Radar."""

    def __init__(self, config: Settings = settings, db: Optional[Any] = None, notifier: Optional[Notifier] = None):
        self.config = config
        self.db = db or get_database(config)
        self.notifier = notifier or Notifier(config)
        self.ai_validator = GeminiDealValidator(config)
        self.brand_validator = BrandValidator(allow_unknown=False)

    async def init(self) -> None:
        await self.db.initialize()

    async def close(self) -> None:
        await self.db.close()

    async def scan_rule(
        self,
        rule: RadarRule,
        exclude_platforms: Optional[list[str]] = None,
        only_platforms: Optional[list[str]] = None,
    ) -> List[dict[str, Any]]:
        """Execute a single radar rule across its configured platforms."""
        found_deals: List[dict[str, Any]] = []

        for platform in rule.platforms:
            if exclude_platforms and platform in exclude_platforms:
                continue
            if only_platforms and platform not in only_platforms:
                continue
                
            try:
                if platform == "amazon":
                    scraper = get_scraper("amazon", self.config)
                    custom_url = rule.search_url_template.get("amazon") if rule.search_url_template else None
                    deals = await scraper.scan_deals(
                        query=rule.query,
                        min_discount=rule.min_discount,
                        max_price=rule.max_price,
                        min_mrp=rule.min_mrp,
                        negative_keywords=rule.negative_keywords,
                        custom_url=custom_url,
                        brand=rule.brand,
                    )
                    found_deals.extend(deals)

                elif platform == "flipkart":
                    scraper = get_scraper("flipkart", self.config)
                    custom_url = rule.search_url_template.get("flipkart") if rule.search_url_template else None
                    deals = await scraper.scan_deals(
                        query=rule.query,
                        min_discount=rule.min_discount,
                        max_price=rule.max_price,
                        min_mrp=rule.min_mrp,
                        negative_keywords=rule.negative_keywords,
                        custom_url=custom_url,
                        brand=rule.brand,
                    )
                    found_deals.extend(deals)

                elif platform == "myntra":
                    scraper = get_scraper("myntra", self.config)
                    custom_url = rule.search_url_template.get("myntra") if rule.search_url_template else None
                    deals = await scraper.scan_deals(
                        query=rule.query,
                        min_discount=rule.min_discount,
                        max_price=rule.max_price,
                        min_mrp=rule.min_mrp,
                        negative_keywords=rule.negative_keywords,
                        custom_url=custom_url,
                    )
                    found_deals.extend(deals)

                elif platform == "bigbasket":
                    scraper = get_scraper("bigbasket", self.config)
                    custom_url = rule.search_url_template.get("bigbasket") if rule.search_url_template else None
                    deals = await scraper.scan_deals(
                        query=rule.query,
                        min_discount=rule.min_discount,
                        max_price=rule.max_price,
                        min_mrp=rule.min_mrp,
                        negative_keywords=rule.negative_keywords,
                        custom_url=custom_url,
                    )
                    found_deals.extend(deals)

                elif platform == "casio":
                    from scrapers.casio import CasioScraper
                    casio_scraper = CasioScraper(self.config)
                    
                    # 1. Direct product tracking via exact URL
                    custom_url = rule.search_url_template.get("casio") if rule.search_url_template else None
                    if custom_url and "/products/" in custom_url:
                        result = await casio_scraper.scrape(custom_url)
                        if result and result.in_stock and result.price is not None:
                            if rule.max_price is not None and result.price > rule.max_price:
                                deals = []
                            else:
                                deals = [{
                                    "title": result.title,
                                    "price": result.price,
                                    "mrp": result.price,  # We don't have explicit MRP from single scrape result
                                    "discount_percent": 0.0,
                                    "url": result.url,
                                    "in_stock": result.in_stock,
                                }]
                        else:
                            deals = []
                    else:
                        # 2. Collection scanning
                        handles_to_scan = set()
                        q_lower = rule.query.lower()
                        if "g-shock" in q_lower or "gshock" in q_lower:
                            handles_to_scan.add("g-shock")
                        if "edifice" in q_lower:
                            handles_to_scan.add("edifice-watches")
                        if "vintage" in q_lower:
                            handles_to_scan.add("casio-vintage")
                        if "enticer" in q_lower:
                            handles_to_scan.add("enticer-men")
                            handles_to_scan.add("enticer-women")
                        
                        if not handles_to_scan or "watch" in q_lower:
                            handles_to_scan.update(["g-shock", "edifice-watches", "casio-vintage", "casio-all-watches"])
                            
                        deals = []
                        for handle in handles_to_scan:
                            collection_deals = await casio_scraper.scan_collection_deals(handle, min_discount=rule.min_discount)
                            deals.extend(collection_deals)

                    for d in deals:
                        d["effective_price"] = d["price"]
                        d["coupon_text"] = None
                        d["platform"] = "casio"
                        # CRITICAL: Since this is the official Casio store, all products are Casio.
                        # We MUST set this so the BrandValidator doesn't reject it as UNKNOWN.
                        d["scraped_brand"] = "Casio"
                    found_deals.extend(deals)

                # Polite delay between platform queries
                await asyncio.sleep(random.uniform(1.0, 2.5))
            except Exception as exc:
                logger.warning("[radar] error scanning rule '%s' on %s: %s", rule.name, platform, exc)

        # Apply confidence-based brand validation (replaces simple substring matching)
        if rule.required_keywords or rule.brand:
            validated_deals = []
            for d in found_deals:
                target_brands = []
                if rule.brand:
                    target_brands.append(rule.brand)
                if rule.required_keywords:
                    target_brands.extend(rule.required_keywords)

                is_trusted = d.get("platform") == "casio"

                bv_result = self.brand_validator.validate(
                    scraped_brand=d.get("scraped_brand"),
                    title=d["title"],
                    target_brands=target_brands,
                    is_trusted_store=is_trusted,
                )
                d["brand_validation"] = {
                    "status": bv_result.brand_status.value,
                    "scraped_brand": bv_result.scraped_brand,
                    "normalized_brand": bv_result.normalized_brand,
                    "target_brand": bv_result.target_brand,
                    "confidence_score": bv_result.confidence_score,
                    "filter_reason": bv_result.filter_reason,
                    "compatibility_phrase": bv_result.matched_compatibility_phrase,
                }

                # Independent check: must contain at least one required keyword if specified
                has_req = False
                if rule.required_keywords:
                    title_lower = d["title"].lower()
                    has_req = any(k.lower() in title_lower for k in rule.required_keywords)
                else:
                    has_req = True

                if bv_result.brand_status == BrandStatus.VERIFIED and has_req:
                    validated_deals.append(d)
                else:
                    logger.info(
                        "[BRAND FILTER] %s '%s' (brand=%s, target=%s, score=%s) — %s",
                        bv_result.brand_status.value,
                        d["title"][:50],
                        bv_result.scraped_brand or "(none)",
                        bv_result.target_brand,
                        bv_result.confidence_score,
                        bv_result.filter_reason,
                    )
            found_deals = validated_deals

        # Apply negative keywords filter if specified
        if rule.negative_keywords:
            neg_set = [k.lower() for k in rule.negative_keywords]
            found_deals = [
                d for d in found_deals
                if not any(neg in d["title"].lower() for neg in neg_set)
            ]

        # Apply price ceiling filter if specified
        if rule.max_price is not None:
            found_deals = [
                d for d in found_deals
                if d.get("effective_price", d["price"]) <= rule.max_price
            ]

        # Apply price floor filter if specified (eradicates straps/pins)
        if rule.min_price is not None:
            found_deals = [
                d for d in found_deals
                if d.get("effective_price", d["price"]) >= rule.min_price
            ]

        return found_deals

    async def process_and_notify_deals(
        self,
        rule: RadarRule,
        exclude_platforms: Optional[list[str]] = None,
        only_platforms: Optional[list[str]] = None,
    ) -> int:
        """Execute a rule and route valid steal deals to the notification channel."""
        logger.info("[radar] Executing rule '%s' across platforms: %s", rule.name, rule.platforms)
        deals = await self.scan_rule(
            rule,
            exclude_platforms=exclude_platforms,
            only_platforms=only_platforms,
        )

        alerts_sent = 0
        has_channel = bool(
            (self.config.telegram_bot_token and self.config.telegram_chat_id)
            or (self.config.whatsapp_phone and self.config.whatsapp_api_key)
        )

        for deal in deals:
            url = deal["url"]
            eff_price = deal.get("effective_price", deal["price"])
            mrp = deal.get("mrp", eff_price)
            disc = deal.get("discount_percent", 0.0)
            coupon = deal.get("coupon_text")

            # 1. Dynamic price-aware de-duplication cache (allows re-alerting on further drops)
            if await self.db.is_deal_recently_notified(url, hours=24, current_price=eff_price):
                continue

            # 2. AI Arbiter: Validate genuine brand & genuine high-value deal (Cloudflare -> Gemini)
            verdict = await self.ai_validator.validate_deal(
                title=deal["title"],
                category=rule.category,
                selling_price=eff_price,
                mrp=mrp,
                discount_percent=disc,
                platform=deal.get("platform", "online"),
                required_brands=rule.required_keywords,
                scraped_brand=deal.get("scraped_brand"),
            )
            if not verdict.is_genuine_steal or verdict.is_accessory_or_knockoff:
                logger.info("[radar] AI Filtered Out '%s': %s", deal["title"][:40], verdict.reason)
                continue

            # 3. Build high-priority alert message with AI model attribution
            coupon_line = f"\n🎟️ *Coupon:* {coupon} (Apply on page!)" if coupon else ""
            deal_badge = "🔥 STEAL DEAL" if disc < 80 else "🚨 PRICING GLITCH / CLEARANCE"
            brand_tag = deal.get("scraped_brand") or "(verified)"

            msg = (
                f"{deal_badge} [{rule.category.upper()}] {deal_badge}\n"
                f"🏷️ *Rule:* {rule.name}\n"
                f"📦 *Item:* {deal['title']}\n"
                f"🏭 *Brand:* {brand_tag}\n"
                f"💰 *Deal Price:* ₹{eff_price:g} (MRP: ₹{mrp:g}){coupon_line}\n"
                f"📉 *Discount:* {disc:.1f}% OFF (Target: >={rule.min_discount}%)\n"
                f"🏪 *Platform:* {deal.get('platform', 'Retailer').title()}\n"
                f"🤖 *AI Arbiter:* {verdict.model_used}\n"
                f"📝 *AI Analysis:* {verdict.reason}\n"
                f"🛒 *BUY NOW:* {url}"
            )

            # Send alert via Telegram/WhatsApp if configured
            if has_channel:
                sent = await self.notifier.send_message(msg)
                if sent:
                    await self.db.log_deal_alert(
                        product_url=url,
                        title=deal["title"],
                        price=deal["price"],
                        effective_price=eff_price,
                        discount_percent=disc,
                        coupon_text=coupon,
                        platform=deal.get("platform"),
                    )
                    alerts_sent += 1
                    logger.info("[radar] Dispatched steal alert for %s at ₹%s", deal["title"][:40], eff_price)
                await asyncio.sleep(0.3)
            else:
                # Mark in log without sending HTTP call
                await self.db.log_deal_alert(
                    product_url=url,
                    title=deal["title"],
                    price=deal["price"],
                    effective_price=eff_price,
                    discount_percent=disc,
                    coupon_text=coupon,
                    platform=deal.get("platform"),
                )

        return alerts_sent

    async def scan_all(
        self,
        category_filter: Optional[str] = None,
        min_discount_override: Optional[float] = None,
        exclude_platforms: Optional[list[str]] = None,
        only_platforms: Optional[list[str]] = None,
    ) -> int:
        """Run a full scan across all rules."""
        await self.init()
        total_alerts = 0
        rules = [r for r in DEFAULT_RADAR_RULES if r.is_active]

        # Load custom rules from DB
        custom_db_rules = await self.db.get_custom_rules(active_only=True)
        for cr in custom_db_rules:
            rules.append(
                RadarRule(
                    name=cr["name"],
                    category=cr.get("category") or "Custom",
                    query=cr["query"],
                    platforms=[p.strip() for p in (cr.get("platforms") or "amazon").split(",")],
                    min_discount=float(cr.get("min_discount") or 70.0),
                    max_price=float(cr["max_price"]) if cr.get("max_price") is not None else None,
                    min_mrp=float(cr["min_mrp"]) if cr.get("min_mrp") is not None else None,
                    negative_keywords=[k.strip() for k in (cr.get("negative_keywords") or "").split(",") if k.strip()],
                    required_keywords=[w.strip().lower() for w in cr["query"].split() if len(w) > 2],
                )
            )

        print(f"\n🌐 Launching Universal Steal Radar across {len(rules)} active rule categories...\n")

        for rule in rules:
            if category_filter and category_filter.lower() not in rule.category.lower() and category_filter.lower() not in rule.name.lower():
                continue

            if min_discount_override is not None:
                rule.min_discount = min_discount_override

            # Skip rule completely if we are isolating platforms and this rule doesn't run on any of them
            if only_platforms and not any(p in only_platforms for p in rule.platforms):
                continue

            print(f"🔍 Scanning [{rule.category}] {rule.name} (>= {rule.min_discount}% on {', '.join(rule.platforms)})...")
            
            alerts_sent = await self.process_and_notify_deals(
                rule,
                exclude_platforms=exclude_platforms,
                only_platforms=only_platforms,
            )
            total_alerts += alerts_sent

        print(f"\n✅ Radar scan complete. Dispatched {total_alerts} new WhatsApp alert(s).\n")
        return total_alerts

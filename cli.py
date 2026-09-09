"""Command line interface.

Commands:
    add     --url <link> [--target-price N] [--percent-drop N] [--platform name]
    list    [--all]
    remove  --id N
    pause   --id N
    resume  --id N
    check   [--id N]
    run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from config import settings
from database import Database
from notifier import Notifier
from scrapers import ScrapeError, get_scraper, resolve_platform
from tracker import Tracker


def _enable_utf8_stdio() -> None:
    """Windows consoles default to cp1252; force UTF-8 so ₹/emoji print cleanly."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_enable_utf8_stdio()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Indian e-commerce price tracker + WhatsApp alerts (Amazon, Flipkart, Myntra, Ajio).",
    )
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="start tracking a product URL")
    p_add.add_argument("--url", required=True, help="full product page URL")
    p_add.add_argument("--target-price", type=float, help="alert when price is <= this (INR)")
    p_add.add_argument("--percent-drop", type=float, help="alert when price drops this many percent vs last check")
    p_add.add_argument(
        "--platform",
        choices=["amazon", "flipkart", "myntra", "ajio", "casio", "bigbasket", "blinkit", "zepto", "instamart"],
        help="override automatic platform detection",
    )

    p_list = sub.add_parser("list", help="show tracked products")
    p_list.add_argument("--all", action="store_true", help="also show paused products")

    p_remove = sub.add_parser("remove", help="stop tracking a product")
    p_remove.add_argument("--id", type=int, required=True)

    p_pause = sub.add_parser("pause", help="pause monitoring of a product")
    p_pause.add_argument("--id", type=int, required=True)

    p_resume = sub.add_parser("resume", help="resume a paused product")
    p_resume.add_argument("--id", type=int, required=True)

    p_check = sub.add_parser("check", help="run a single monitoring pass now")
    p_check.add_argument("--id", type=int, help="only check this product id")

    p_scan = sub.add_parser("scan-deals", help="scan Casio / G-Shock collections for high discount deals")
    p_scan.add_argument("--collection", default="g-shock", help="collection slug (default: g-shock)")
    p_scan.add_argument("--min-discount", type=float, default=70.0, help="minimum discount percent (default: 70)")
    p_scan.add_argument("--notify", action="store_true", help="send WhatsApp notification for found deals")

    p_steals = sub.add_parser("scan-steals", help="scan all sniper categories and master clearance feeds for steal deals & glitches")
    p_steals.add_argument("--category", help="filter by category (e.g. tech, fashion, nutrition, storage, amazonbasics, etc.)")
    p_steals.add_argument("--min-discount", type=float, help="override minimum discount percent")

    p_radar = sub.add_parser("radar", help="launch autonomous 24/7 background deal radar")
    p_radar.add_argument("--interval-seconds", type=int, default=600, help="seconds between radar cycles (default: 600s)")

    p_add_rule = sub.add_parser("add-rule", help="add a custom deal hunting sniper rule")
    p_add_rule.add_argument("--name", required=True, help="descriptive rule name")
    p_add_rule.add_argument("--query", required=True, help="search keyword query")
    p_add_rule.add_argument("--category", default="Custom", help="category name")
    p_add_rule.add_argument("--platforms", default="amazon,flipkart", help="comma-separated platforms")
    p_add_rule.add_argument("--min-discount", type=float, default=70.0, help="minimum discount percent")
    p_add_rule.add_argument("--max-price", type=float, help="maximum price ceiling (INR)")
    p_add_rule.add_argument("--min-mrp", type=float, help="minimum baseline MRP (INR)")
    p_add_rule.add_argument("--negative-keywords", default="", help="comma-separated keywords to reject")

    sub.add_parser("list-rules", help="list all pre-configured and custom radar sniper rules")

    p_qc = sub.add_parser("qcommerce-deals", help="hunt for 80%%-95%% clearance deals across Quick Commerce (BigBasket, Blinkit, Zepto, Instamart)")
    p_qc.add_argument("--min-discount", type=float, default=80.0, help="minimum discount percent (default: 80)")
    p_qc.add_argument("--pincode", default="560103", help="delivery pincode (default: 560103)")

    sub.add_parser("run", help="start the background scheduler")

    return parser


# ------------------------------------------------------------------ handlers
async def _cmd_add(args) -> int:
    if args.target_price is None and args.percent_drop is None:
        print("Error: provide --target-price or --percent-drop (or both).")
        return 2
    if not args.url.startswith(("http://", "https://")):
        print("Error: --url must be a full http(s) link.")
        return 2

    try:
        platform = args.platform or await resolve_platform(args.url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    # Try to grab the current title/price so the row starts with real data.
    scraper = get_scraper(platform, settings)
    title, price = None, None
    try:
        result = await scraper.scrape(args.url)
        title, price = result.title, result.price
        if not result.in_stock:
            print("Note: product currently appears out of stock.")
    except ScrapeError as exc:
        print(f"Warning: could not scrape the page right now ({exc}).")
        print("  Adding anyway - the first `check`/`run` pass will fill in the price.")

    db = Database(settings.database_path)
    await db.initialize()
    try:
        product_id = await db.add_product(
            url=args.url,
            platform=platform,
            title=title,
            initial_price=price,
            target_price=args.target_price,
            percentage_drop_target=args.percent_drop,
        )
    finally:
        await db.close()

    print(f"Added product #{product_id} [{platform}]")
    print(f"  title:     {title or '(unknown yet)'}")
    print(f"  price:     {'INR ' + str(price) if price is not None else '?'}")
    if args.target_price is not None:
        print(f"  target:    INR {args.target_price:g}")
    if args.percent_drop is not None:
        print(f"  %-drop:    {args.percent_drop:g}%")
    return 0


async def _cmd_list(args) -> int:
    db = Database(settings.database_path)
    await db.initialize()
    try:
        products = await db.get_products(active_only=not args.all)
    finally:
        await db.close()

    if not products:
        print("No products tracked. Add one with:")
        print('  python main.py add --url "<product-link>" --target-price 1499')
        return 0

    print(f"{'ID':<4} {'Platform':<9} {'Active':<7} {'Price':<12} {'Target':<12} Title")
    print("-" * 100)
    for p in products:
        price = f"INR {p.current_price:g}" if p.current_price is not None else "?"
        if p.target_price is not None:
            target = f"INR {p.target_price:g}"
        elif p.percentage_drop_target is not None:
            target = f"{p.percentage_drop_target:g}%"
        else:
            target = "-"
        title = (p.title or p.url)[:70]
        print(
            f"{p.id:<4} {p.platform:<9} {'yes' if p.is_active else 'no':<7} "
            f"{price:<12} {target:<12} {title}"
        )
    return 0


async def _cmd_remove(args) -> int:
    db = Database(settings.database_path)
    await db.initialize()
    try:
        product = await db.get_product(args.id)
        if product is None:
            print(f"No product with id {args.id}.")
            return 1
        await db.remove_product(args.id)
    finally:
        await db.close()
    print(f"Removed #{args.id} ({(product.title or product.url)[:60]}).")
    return 0


async def _cmd_pause(args) -> int:
    return await _toggle_active(args, active=False)


async def _cmd_resume(args) -> int:
    return await _toggle_active(args, active=True)


async def _toggle_active(args, active: bool) -> int:
    db = Database(settings.database_path)
    await db.initialize()
    try:
        product = await db.get_product(args.id)
        if product is None:
            print(f"No product with id {args.id}.")
            return 1
        await db.set_active(args.id, active)
    finally:
        await db.close()
    print(f"Product #{args.id} {'resumed' if active else 'paused'}.")
    return 0


async def _cmd_check(args) -> int:
    db = Database(settings.database_path)
    await db.initialize()
    try:
        tracker = Tracker(db, Notifier(settings), settings)
        if args.id is not None:
            product = await db.get_product(args.id)
            if product is None:
                print(f"No product with id {args.id}.")
                return 1
            if not product.is_active:
                print("Product is paused; resume it first.")
                return 1
            await tracker.check_product(product)
            print(f"Checked #{args.id} ({(product.title or product.url)[:50]}).")
        else:
            sent = await tracker.run_once()
            print(f"Checked all active products; {sent} alert(s) sent.")
    finally:
        await db.close()
    return 0


async def _cmd_run(args) -> int:
    db = Database(settings.database_path)
    await db.initialize()
    if not settings.whatsapp_phone or not settings.whatsapp_api_key:
        print("WARNING: WHATSAPP_PHONE / WHATSAPP_API_KEY are not set in .env - alerts will NOT be sent.")
    tracker = Tracker(db, Notifier(settings), settings)
    try:
        await tracker.run_forever()
    finally:
        await db.close()
    return 0


async def _cmd_scan_deals(args) -> int:
    from scrapers.casio import CasioScraper
    scraper = CasioScraper(settings)
    print(f"Scanning Casio collection '{args.collection}' for deals with >={args.min_discount}% discount...")
    deals = await scraper.scan_collection_deals(args.collection, min_discount=args.min_discount)
    if not deals:
        print(f"No deals currently found matching >={args.min_discount}% discount.")
        return 0

    print(f"\nFound {len(deals)} steal deal(s):")
    notifier = Notifier(settings) if args.notify else None
    for d in deals:
        print(f" - {d['title']}: \u20B9{d['price']:g} (MRP: \u20B9{d['mrp']:g}) -> {d['discount_percent']:.1f}% OFF! Link: {d['url']}")
        if notifier:
            deal_msg = (
                f"\U0001F6A8 *G-SHOCK STEAL DEAL ({d['discount_percent']:.0f}% OFF!)* \U0001F6A8\n"
                f"\U0001F4E6 *Watch:* {d['title']}\n"
                f"\U0001F4C9 *Deal Price:* \u20B9{d['price']:g} (MRP: \u20B9{d['mrp']:g})\n"
                f"\U0001F3AF *Discount:* {d['discount_percent']:.1f}% OFF (Target: >={args.min_discount}%)\n"
                f"\U0001F6D2 *Buy Now:* {d['url']}"
            )
            await notifier.send_whatsapp(deal_msg)
    return 0


async def _cmd_scan_steals(args) -> int:
    from radar import StealRadar
    radar = StealRadar(settings)
    try:
        await radar.scan_all(
            category_filter=args.category,
            min_discount_override=args.min_discount,
        )
    finally:
        await radar.close()
    return 0


async def _cmd_radar(args) -> int:
    from radar import StealRadar
    print(f"🛰️ Launching 24/7 Steal Radar Loop (polling every {args.interval_seconds}s)...")
    radar = StealRadar(settings)
    try:
        while True:
            await radar.scan_all()
            await asyncio.sleep(args.interval_seconds)
    finally:
        await radar.close()
    return 0


async def _cmd_add_rule(args) -> int:
    db = Database(settings.database_path)
    await db.initialize()
    try:
        rule_id = await db.add_custom_rule(
            name=args.name,
            query=args.query,
            category=args.category,
            platforms=args.platforms,
            min_discount=args.min_discount,
            max_price=args.max_price,
            min_mrp=args.min_mrp,
            negative_keywords=args.negative_keywords,
        )
        print(f"Added custom radar sniper rule #{rule_id}: '{args.name}' ({args.query})")
    finally:
        await db.close()
    return 0


async def _cmd_list_rules(args) -> int:
    from radar_rules import DEFAULT_RADAR_RULES
    db = Database(settings.database_path)
    await db.initialize()
    try:
        print("\n=== Pre-configured Master Radar Rules ===")
        for i, r in enumerate(DEFAULT_RADAR_RULES, start=1):
            price_cond = f"<= ₹{r.max_price:g}" if r.max_price else f">= {r.min_discount}%"
            print(f" [{i}] [{r.category}] {r.name} -> Target: {price_cond} (Platforms: {', '.join(r.platforms)})")

        custom_rules = await db.get_custom_rules(active_only=False)
        if custom_rules:
            print("\n=== Custom User Sniper Rules ===")
            for cr in custom_rules:
                status = "active" if cr.get("is_active") else "paused"
                print(f" #{cr['id']} [{cr.get('category', 'Custom')}] {cr['name']} -> Query: '{cr['query']}' | Target: >={cr.get('min_discount')}% [{status}]")
        print()
    finally:
        await db.close()
    return 0


async def _cmd_qcommerce_deals(args) -> int:
    from qcommerce_radar import QuickCommerceRadar
    radar = QuickCommerceRadar(settings)
    results = await radar.scan_all_qcommerce(min_discount=args.min_discount, pincode=args.pincode)

    total_found = 0
    print("\n" + "=" * 65)
    print(f"⚡ QUICK COMMERCE >={args.min_discount}% CLEARANCE & STEAL DEALS")
    print("=" * 65)

    for platform, deals in results.items():
        if deals:
            total_found += len(deals)
            print(f"\n🏪 [{platform.upper()}] ({len(deals)} steal deals):")
            for d in deals:
                print(f"  ✨ {d['title'][:48]}")
                print(f"     Price: ₹{d['price']:g} (MRP: ₹{d['mrp']:g}) -> {d['discount_percent']:.1f}% OFF!")
                print(f"     Buy: {d['url']}")

    if total_found == 0:
        print(f"\n💤 No active >={args.min_discount}% clearance deals found right now.")
    else:
        print(f"\n🎯 Total Quick Commerce Steals Found: {total_found}")
    print()
    return 0


# -------------------------------------------------------------------- dispatch
def run(args: argparse.Namespace) -> int:
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        )

    handlers = {
        "add": _cmd_add,
        "list": _cmd_list,
        "remove": _cmd_remove,
        "pause": _cmd_pause,
        "resume": _cmd_resume,
        "check": _cmd_check,
        "scan-deals": _cmd_scan_deals,
        "scan-steals": _cmd_scan_steals,
        "qcommerce-deals": _cmd_qcommerce_deals,
        "radar": _cmd_radar,
        "add-rule": _cmd_add_rule,
        "list-rules": _cmd_list_rules,
        "run": _cmd_run,
    }
    return asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    import sys
    parser = build_parser()
    args = parser.parse_args()
    try:
        sys.exit(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
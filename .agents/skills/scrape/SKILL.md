---
name: scrape
description: Extract data from e-commerce websites and web pages using Scrapling / HTTP / browser engines.
triggers:
  - scrape
  - scrape url
  - extract price
  - test scraper
---

# Scrape & Price Extraction Skill

When invoked to scrape or test a target URL:

1. **Platform Detection**: Detect if target is Amazon, Flipkart, Myntra, Ajio, or a general website.
2. **Strategy Selection**:
   - For static/fast pages: Use `scrapling.fetchers.Fetcher(impersonate="chrome")` with TLS spoofing.
   - For JS-heavy or bot-protected pages (Myntra/Ajio): Use `scrapling.fetchers.StealthyFetcher`.
3. **Adaptive Extraction**:
   - Extract title, current price, MRP/original price, stock status.
   - Use adaptive selectors (`adaptive=True`) to handle layout/class changes automatically.
4. **Return Format**: Return a clean JSON object with title, price, in_stock, platform, and timestamp.

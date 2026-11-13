"""Flipkart Interactive Login Helper.

Launches a visible Chromium window. You log into your Flipkart account (Sriram),
and this script saves your session cookies and profile locally so all local snipers
see your exact personalized VIP prices, Plus discounts, and pincode.
"""

import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_flipkart_profile")
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flipkart_session_cookies.json")


async def main():
    print("=" * 70)
    print("🔐 FLIPKART ONE-TIME LOGIN SESSION BUILDER")
    print("=" * 70)
    print("Launching visible browser with persistent session...")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            channel="chrome",  # uses installed Google Chrome if available, else chromium
            viewport={"width": 1280, "height": 850},
            args=["--disable-blink-features=AutomationControlled"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        )

        page = context.pages[0] if context.pages else await context.new_page()

        print("\nNavigating to Flipkart Login page...")
        try:
            await page.goto("https://www.flipkart.com/account/login?ret=/", wait_until="domcontentloaded")
        except Exception:
            pass

        print("\n" + "*" * 70)
        print("👉 In the open browser window:")
        print("   1. Enter your Mobile Number and OTP to log into your account.")
        print("   2. Verify that your name (Sriram) appears at the top right.")
        print("   3. Enter your default delivery pincode if prompted.")
        print("   4. Once logged in, COME BACK TO THIS TERMINAL AND PRESS [ENTER].")
        print("*" * 70 + "\n")

        # Wait for user confirmation in console
        await asyncio.to_thread(input, "Press [ENTER] here once you have logged in on Flipkart...")

        # Extract all cookies
        cookies = await context.cookies(["https://www.flipkart.com", "https://flipkart.com"])

        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)

        print("\n" + "=" * 70)
        print(f"✅ SUCCESS! Captured {len(cookies)} session cookies.")
        print(f"📁 Session Profile Saved to: {PROFILE_DIR}")
        print(f"📄 Cookie Export Saved to : {COOKIES_FILE}")
        print("=" * 70)
        print("Your local snipers will now see your exact personalized pricing (Plus/VIP/pincode)!")
        
        await context.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nLogin cancelled.")


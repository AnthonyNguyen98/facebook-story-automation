from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


async def main() -> None:
    state = Path("meta_storage_state.json").resolve()
    if not state.exists():
        raise SystemExit(f"Missing session file: {state}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            storage_state=str(state),
            viewport={"width": 1440, "height": 1000},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
        )
        page = await context.new_page()
        await page.goto("https://business.facebook.com/latest/home", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(3000)
        print(f"FINAL_URL={page.url}")
        if "login" in page.url.lower():
            print("META_LOCAL_SESSION=FAIL")
        else:
            print("META_LOCAL_SESSION=PASS")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

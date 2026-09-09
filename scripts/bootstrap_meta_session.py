from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


async def main():
    out = Path("meta_storage_state.json")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width":1440,"height":1000})
        page = await context.new_page()
        await page.goto("https://business.facebook.com/", wait_until="domcontentloaded")
        print("Đăng nhập Meta Business Suite trong cửa sổ Chromium. Sau khi thấy Business Suite, quay lại terminal và nhấn Enter.")
        input()
        await context.storage_state(path=str(out))
        print(f"Saved: {out.resolve()}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from playwright.async_api import async_playwright
import json

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        errors = []
        page.on("console", lambda msg: errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda err: errors.append(f"PAGE ERROR: {err}"))
        
        print("Loading dashboard...")
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        await page.wait_for_timeout(10000)
        
        if errors:
            print("ERRORS FOUND:")
            for e in errors[:20]:
                print(f"  {e}")
        else:
            print("No JavaScript errors found")
        
        # Check if TradeMap instances were created
        tm_check = await page.evaluate("""() => {
            return {
                tmTab: typeof window._tmTab,
                tmDetail: typeof window._tmDetail,
                tmTabType: window._tmTab?.constructor?.name,
                tmDetailType: window._tmDetail?.constructor?.name,
            };
        }""")
        print(f"TradeMap check: {json.dumps(tm_check, indent=2)}")
        
        # Check if strategy detail opened
        detail_check = await page.evaluate("""() => {
            return {
                detailActive: document.querySelector('#strategy-detail')?.classList.contains('active'),
                mainHidden: document.querySelector('#mainContent')?.classList.contains('hidden'),
            };
        }""")
        print(f"Detail check: {json.dumps(detail_check, indent=2)}")
        
        await browser.close()

asyncio.run(main())
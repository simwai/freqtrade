import asyncio
from playwright.async_api import async_playwright
import json

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Capture console messages
        page.on("console", lambda msg: print(f"CONSOLE [{msg.type}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"PAGE ERROR: {err}"))
        
        # Navigate to the URL
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        
        # Wait for the page to load
        await page.wait_for_timeout(10000)
        
        # Click Trades tab
        trades_tab = await page.query_selector("text=Trades")
        if trades_tab:
            await trades_tab.click()
            await page.wait_for_timeout(5000)
        
        # Check the renderTrades function
        render_trades_source = await page.evaluate("""() => {
            if (typeof renderTrades === 'function') {
                return renderTrades.toString();
            }
            return 'not found';
        }""")
        print(f"renderTrades source (first 8000 chars): {render_trades_source[:8000]}")
        
        # Check the mountTradeMap function
        mount_source = await page.evaluate("""() => {
            if (typeof mountTradeMap === 'function') {
                return mountTradeMap.toString();
            }
            return 'not found';
        }""")
        print(f"\nmountTradeMap source (first 8000 chars): {mount_source[:8000]}")
        
        # Check the tlPaint function
        paint_source = await page.evaluate("""() => {
            if (typeof tlPaint === 'function') {
                return tlPaint.toString();
            }
            return 'not found';
        }""")
        print(f"\ntlPaint source (first 8000 chars): {paint_source[:8000]}")
        
        # Check the tlEnsureCandles function
        ensure_source = await page.evaluate("""() => {
            if (typeof tlEnsureCandles === 'function') {
                return tlEnsureCandles.toString();
            }
            return 'not found';
        }""")
        print(f"\ntlEnsureCandles source (first 8000 chars): {ensure_source[:8000]}")
        
        await browser.close()

asyncio.run(main())
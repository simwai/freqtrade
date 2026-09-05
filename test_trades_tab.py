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
        
        # Navigate DIRECTLY to the URL with strategy hash parameter
        print("Navigating directly to http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick")
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        
        # Wait for the fix to execute and data to load
        await page.wait_for_timeout(15000)
        
        # Click Trades tab
        trades_tab = await page.query_selector("text=Trades")
        if trades_tab:
            await trades_tab.click()
            await page.wait_for_timeout(5000)
        
        # Check trade map canvas in Trades tab (3rd canvas)
        canvas_data = await page.evaluate("""() => {
            const canvases = document.querySelectorAll('canvas');
            const c = canvases[2];
            if (!c) return { error: 'No canvas found' };
            const ctx = c.getContext('2d');
            const imgData = ctx.getImageData(0, 0, c.width, c.height);
            let nonTransparent = 0;
            for (let y = 0; y < c.height; y += 20) {
                for (let x = 0; x < c.width; x += 50) {
                    const idx = (y * c.width + x) * 4;
                    if (imgData.data[idx + 3] > 0) nonTransparent++;
                }
            }
            return { width: c.width, height: c.height, nonTransparentPixels: nonTransparent };
        }""")
        print(f"Trades tab trade map canvas: {json.dumps(canvas_data, indent=2)}")
        
        await page.screenshot(path="dashboard_trades_tab_test.png", full_page=True)
        
        await browser.close()

asyncio.run(main())
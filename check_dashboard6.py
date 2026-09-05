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
        
        # Now let's manually call the render function
        render_result = await page.evaluate("""() => {
            try {
                // Check if tlRender exists and call it
                if (typeof tlRender === 'function') {
                    const result = tlRender();
                    return { success: true, result: result };
                } else {
                    return { success: false, error: 'tlRender not found' };
                }
            } catch (e) {
                return { success: false, error: e.toString(), stack: e.stack };
            }
        }""")
        print(f"tlRender result: {json.dumps(render_result, indent=2)}")
        
        # Check canvas again after render
        canvas_data = await page.evaluate("""() => {
            const canvases = document.querySelectorAll('canvas');
            const c = canvases[2]; // trade map canvas
            const ctx = c.getContext('2d');
            const imgData = ctx.getImageData(0, 0, c.width, c.height);
            
            const samples = [];
            for (let y = 0; y < c.height; y += 50) {
                for (let x = 0; x < c.width; x += 100) {
                    const idx = (y * c.width + x) * 4;
                    if (imgData.data[idx + 3] > 0) {
                        samples.push({ x, y, r: imgData.data[idx], g: imgData.data[idx+1], b: imgData.data[idx+2], a: imgData.data[idx+3] });
                    }
                }
            }
            return { width: c.width, height: c.height, nonTransparentPixels: samples.length, samples: samples.slice(0, 20) };
        }""")
        print(f"\nCanvas after render: {json.dumps(canvas_data, indent=2)}")
        
        # Take a screenshot
        await page.screenshot(path="dashboard_after_render.png", full_page=True)
        
        # Let's also check what data the trade map has
        trade_data_check = await page.evaluate("""() => {
            // Check the trade data loaded for the current strategy
            // The data should be in the _tlData or similar
            return {
                tlTab: window._tlTab,
                tlDetail: window._tlDetail,
                tlData: window._tlData,
                tradesData: window.tradesData,
            };
        }""")
        print(f"\nTrade data check: {json.dumps(trade_data_check, indent=2)}")
        
        # Check the loadTradeRun function
        load_check = await page.evaluate("""() => {
            try {
                if (typeof loadTradeRun === 'function') {
                    const result = loadTradeRun();
                    return { success: true, result: result };
                }
                return { success: false, error: 'loadTradeRun not found' };
            } catch (e) {
                return { success: false, error: e.toString() };
            }
        }""")
        print(f"\nloadTradeRun result: {json.dumps(load_check, indent=2)}")
        
        await browser.close()

asyncio.run(main())
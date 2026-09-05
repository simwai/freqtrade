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
        
        # Try to manually create the trade map instance and load data
        manual_result = await page.evaluate("""() => {
            try {
                // First, ensure the mount exists
                if (!window._tmTab) {
                    window._tmTab = mountTradeMap('tm-tab');
                    console.log('Created _tmTab');
                }
                
                // Now load the trade data
                const key = "ScreenerDpoBbwpWick__2026-09-03_14-51-57";
                const sel = $('tradeRun');
                if (sel) sel.value = key;
                
                return loadTradeRun();
            } catch (e) {
                return { error: e.toString(), stack: e.stack };
            }
        }""")
        print(f"Manual load result: {manual_result}")
        
        # Wait for fetch
        await page.wait_for_timeout(8000)
        
        # Check state after load - only return simple values
        state = await page.evaluate("""() => {
            const tab = window._tmTab;
            return {
                hasTmTab: !!tab,
                tradesCount: tab ? tab.trades?.length : 0,
                candlesCount: tab ? tab.candles?.length : 0,
                pair: tab ? tab.pair : null,
                runKey: tab ? tab.runKey : null,
                hasTradeCache: !!window.tradeCache,
                cacheKeys: window.tradeCache ? Object.keys(window.tradeCache) : [],
            };
        }""")
        print(f"\nState after manual load: {json.dumps(state, indent=2)}")
        
        # Try to render
        if state.get('hasTmTab'):
            render_result = await page.evaluate("""() => {
                try {
                    tlRender(window._tmTab);
                    return { success: true };
                } catch (e) {
                    return { error: e.toString(), stack: e.stack };
                }
            }""")
            print(f"\nRender result: {json.dumps(render_result, indent=2)}")
        
        # Wait for rendering
        await page.wait_for_timeout(3000)
        
        # Check canvas
        canvas_data = await page.evaluate("""() => {
            const canvases = document.querySelectorAll('canvas');
            const c = canvases[2];
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
        
        await page.screenshot(path="dashboard_final.png", full_page=True)
        
        await browser.close()

asyncio.run(main())
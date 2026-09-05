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
        
        # Create trade map instance, fetch data, and render
        await page.evaluate("""() => {
            // Create the trade map instance
            if (!window._tmTab) {
                window._tmTab = mountTradeMap('tm-tab');
            }
            
            // Fetch and cache the data
            const key = "ScreenerDpoBbwpWick__2026-09-03_14-51-57";
            const sel = $('tradeRun');
            if (sel) sel.value = key;
            
            const bust = encodeURIComponent(LAB.built || '');
            return fetch(`trades/${encodeURIComponent(key)}.json?v=${bust}`)
                .then(r => r.ok ? r.json() : Promise.reject(r.status))
                .then(d => {
                    window.tradeCache = window.tradeCache || {};
                    window.tradeCache[key] = d;
                    // Now call renderTrades which should call tlSetRun and tlRender
                    renderTrades(d);
                    return { success: true };
                })
                .catch(e => ({ success: false, error: e.toString() }));
        }""")
        
        # Wait for rendering
        await page.wait_for_timeout(5000)
        
        # Check the trade map instance state
        state = await page.evaluate("""() => {
            const tab = window._tmTab;
            return {
                hasTmTab: !!tab,
                tradesCount: tab?.trades?.length || 0,
                candlesCount: tab?.candles?.length || 0,
                pair: tab?.pair,
                runKey: tab?.runKey,
                tf: tab?.tf,
                mode: tab?.mode,
                shownCount: tab?.shown?.length || 0,
            };
        }""")
        print(f"Trade map state: {json.dumps(state, indent=2)}")
        
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
        print(f"\nCanvas: {json.dumps(canvas_data, indent=2)}")
        
        await page.screenshot(path="dashboard_rendered.png", full_page=True)
        
        await browser.close()

asyncio.run(main())
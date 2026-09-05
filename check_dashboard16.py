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
        
        # Check the initialization code that creates _tmTab
        init_check = await page.evaluate("""() => {
            // Check if there's an init function that creates _tmTab
            return {
                _tlInstances: window._tlInstances,
                _tmTab_global: typeof _tmTab,
                _tmTab_window: typeof window._tmTab,
                mountTradeMap_called: document.getElementById('tm-tab')?.classList.contains('tl-mount'),
            };
        }""")
        print(f"Init check: {json.dumps(init_check, indent=2)}")
        
        # Manually call tlSetRun to see what happens
        tlsetrun_result = await page.evaluate("""() => {
            const key = "ScreenerDpoBbwpWick__2026-09-03_14-51-57";
            const bust = encodeURIComponent(LAB.built || '');
            return fetch(`trades/${encodeURIComponent(key)}.json?v=${bust}`)
                .then(r => r.ok ? r.json() : Promise.reject(r.status))
                .then(d => {
                    console.log('Data:', d.strategy, d.trades.length);
                    // Manually call tlSetRun with the global _tmTab
                    window._tmTab = window._tmTab || mountTradeMap('tm-tab');
                    tlSetRun(window._tmTab, d, '5m', 'spot');
                    console.log('tlSetRun called');
                    return { success: true, trades: window._tmTab.trades?.length };
                })
                .catch(e => ({ success: false, error: e.toString(), stack: e.stack }));
        }""")
        print(f"\ntlSetRun result: {json.dumps(tlsetrun_result, indent=2)}")
        
        # Wait
        await page.wait_for_timeout(3000)
        
        # Check state
        state = await page.evaluate("""() => {
            const tab = window._tmTab;
            return {
                tradesCount: tab?.trades?.length || 0,
                candlesCount: tab?.candles?.length || 0,
                pair: tab?.pair,
                runKey: tab?.runKey,
                shownCount: tab?.shown?.length || 0,
            };
        }""")
        print(f"\nState after tlSetRun: {json.dumps(state, indent=2)}")
        
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
        
        await page.screenshot(path="dashboard_tlsetrun.png", full_page=True)
        
        await browser.close()

asyncio.run(main())
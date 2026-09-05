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
        
        # Check LAB object
        lab_info = await page.evaluate("""() => {
            return {
                LAB: window.LAB,
                tradeCache: window.tradeCache,
                _renderedTradeData: window._renderedTradeData,
            };
        }""")
        print(f"LAB info: {json.dumps(lab_info, indent=2, default=str)}")
        
        # Check the trade run select element
        trade_run_select = await page.query_selector("#tradeRun")
        if trade_run_select:
            options = await trade_run_select.query_selector_all("option")
            print(f"\nTrade run select options: {len(options)}")
            for opt in options:
                text = await opt.inner_text()
                value = await opt.get_attribute("value")
                print(f"  {value}: {text}")
        else:
            print("\nNo #tradeRun element found")
            # Search for it
            all_selects = await page.query_selector_all("select")
            for sel in all_selects:
                id_val = await sel.get_attribute("id")
                class_val = await sel.get_attribute("class")
                if id_val and 'run' in id_val.lower():
                    print(f"  Found select: id={id_val}, class={class_val}")
        
        # Try to manually call loadTradeRun with the correct key
        # The key should be like "ScreenerDpoBbwpWick__2026-09-03_14-51-57"
        load_result = await page.evaluate("""() => {
            const key = "ScreenerDpoBbwpWick__2026-09-03_14-51-57";
            const sel = $('tradeRun');
            if (sel) {
                sel.value = key;
            }
            return loadTradeRun();
        }""")
        print(f"\nManual loadTradeRun result: {json.dumps(load_result, indent=2, default=str)}")
        
        # Wait a bit for the fetch to complete
        await page.wait_for_timeout(5000)
        
        # Check if data is loaded now
        lab_info2 = await page.evaluate("""() => {
            return {
                tradeCache: window.tradeCache,
                _renderedTradeData: window._renderedTradeData,
                tlTab: window._tlTab,
            };
        }""")
        print(f"\nLAB after load: {json.dumps(lab_info2, indent=2, default=str)}")
        
        # Now try to render
        render_result = await page.evaluate("""() => {
            try {
                if (typeof tlRender === 'function' && window._tlTab) {
                    return tlRender(window._tlTab);
                }
                return { error: 'tlRender or _tlTab not available' };
            } catch (e) {
                return { error: e.toString(), stack: e.stack };
            }
        }""")
        print(f"\nRender result: {json.dumps(render_result, indent=2, default=str)}")
        
        # Check canvas
        await page.wait_for_timeout(2000)
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
        print(f"\nCanvas after manual load: {json.dumps(canvas_data, indent=2)}")
        
        await page.screenshot(path="dashboard_after_manual_load.png", full_page=True)
        
        await browser.close()

asyncio.run(main())
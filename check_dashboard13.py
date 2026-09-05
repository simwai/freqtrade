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
        
        # Check the $ function and tradeCache
        check = await page.evaluate("""() => {
            return {
                dollarFn: typeof $,
                tradeCache: typeof tradeCache,
                tradeCacheValue: window.tradeCache,
                _renderedTradeData: typeof window._renderedTradeData,
                tradeStatus: !!document.getElementById('tradeStatus'),
                tradeRun: !!document.getElementById('tradeRun'),
            };
        }""")
        print(f"Check: {json.dumps(check, indent=2)}")
        
        # Try calling loadTradeRun and see what happens step by step
        result = await page.evaluate("""() => {
            const key = "ScreenerDpoBbwpWick__2026-09-03_14-51-57";
            const sel = $('tradeRun');
            console.log('sel:', sel, 'value:', sel?.value);
            if (sel) sel.value = key;
            console.log('sel.value after:', sel?.value);
            
            const status = $('tradeStatus');
            console.log('status:', status);
            
            const bust = encodeURIComponent(LAB.built || '');
            console.log('bust:', bust);
            const url = `trades/${encodeURIComponent(key)}.json?v=${bust}`;
            console.log('url:', url);
            
            return fetch(url)
                .then(r => {
                    console.log('Response:', r.status, r.ok);
                    return r.ok ? r.json() : Promise.reject(r.status);
                })
                .then(d => {
                    console.log('Data:', d.strategy, d.trades?.length);
                    window.tradeCache = window.tradeCache || {};
                    window.tradeCache[key] = d;
                    console.log('Cache set, keys:', Object.keys(window.tradeCache));
                    return { success: true, trades: d.trades?.length, cacheKeys: Object.keys(window.tradeCache) };
                })
                .catch(e => {
                    console.log('Error:', e);
                    return { success: false, error: e.toString() };
                });
        }""")
        print(f"\nStep by step result: {json.dumps(result, indent=2)}")
        
        # Wait a bit
        await page.wait_for_timeout(3000)
        
        # Check cache again
        cache = await page.evaluate("""() => {
            return {
                tradeCacheKeys: window.tradeCache ? Object.keys(window.tradeCache) : [],
                tradeCacheLength: window.tradeCache ? Object.keys(window.tradeCache).length : 0,
            };
        }""")
        print(f"\nCache after: {json.dumps(cache, indent=2)}")
        
        # Now try to call renderTrades manually
        if cache.get('tradeCacheLength', 0) > 0:
            render_result = await page.evaluate("""() => {
                try {
                    const key = "ScreenerDpoBbwpWick__2026-09-03_14-51-57";
                    const data = window.tradeCache[key];
                    if (data) {
                        renderTrades(data);
                        return { success: true };
                    }
                    return { error: 'No data in cache' };
                } catch (e) {
                    return { error: e.toString(), stack: e.stack };
                }
            }""")
            print(f"\nManual renderTrades result: {json.dumps(render_result, indent=2)}")
        
        await browser.close()

asyncio.run(main())
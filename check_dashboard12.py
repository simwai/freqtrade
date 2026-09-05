import asyncio
from playwright.async_api import async_playwright
import json

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Capture network requests
        requests = []
        page.on("request", lambda req: requests.append({
            'url': req.url,
            'method': req.method,
        }))
        
        responses = []
        page.on("response", lambda resp: responses.append({
            'url': resp.url,
            'status': resp.status,
        }))
        
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
        
        # Create the trade map instance and load data
        await page.evaluate("""() => {
            if (!window._tmTab) {
                window._tmTab = mountTradeMap('tm-tab');
            }
            const key = "ScreenerDpoBbwpWick__2026-09-03_14-51-57";
            const sel = $('tradeRun');
            if (sel) sel.value = key;
            loadTradeRun();
        }""")
        
        # Wait for fetch
        await page.wait_for_timeout(8000)
        
        # Check network requests for trades
        trade_requests = [r for r in requests if 'trades/' in r['url']]
        print(f"Trade requests: {len(trade_requests)}")
        for r in trade_requests:
            print(f"  {r['method']} {r['url']}")
        
        trade_responses = [r for r in responses if 'trades/' in r['url']]
        print(f"\nTrade responses: {len(trade_responses)}")
        for r in trade_responses:
            print(f"  {r['status']} {r['url']}")
        
        # Check all responses
        all_responses = [r for r in responses if r['status'] >= 400]
        print(f"\nError responses: {len(all_responses)}")
        for r in all_responses:
            print(f"  {r['status']} {r['url']}")
        
        # Check state
        state = await page.evaluate("""() => {
            return {
                tradeCacheKeys: window.tradeCache ? Object.keys(window.tradeCache) : [],
                renderedDataKeys: window._renderedTradeData ? Object.keys(window._renderedTradeData) : [],
            };
        }""")
        print(f"\nCache state: {json.dumps(state, indent=2)}")
        
        # Try to manually fetch and check
        fetch_result = await page.evaluate("""() => {
            const key = "ScreenerDpoBbwpWick__2026-09-03_14-51-57";
            return fetch(`trades/${encodeURIComponent(key)}.json?v=test`)
                .then(r => {
                    console.log('Fetch status:', r.status);
                    return r.json();
                })
                .then(d => {
                    console.log('Data loaded:', d.strategy, d.trades?.length);
                    return { success: true, trades: d.trades?.length };
                })
                .catch(e => {
                    console.log('Fetch error:', e);
                    return { success: false, error: e.toString() };
                });
        }""")
        print(f"\nManual fetch result: {json.dumps(fetch_result, indent=2)}")
        
        await browser.close()

asyncio.run(main())
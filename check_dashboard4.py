import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Capture network requests
        requests = []
        page.on("request", lambda req: requests.append({
            'url': req.url,
            'method': req.method,
            'resource_type': req.resource_type
        }))
        
        responses = []
        page.on("response", lambda resp: responses.append({
            'url': resp.url,
            'status': resp.status,
            'headers': dict(resp.headers)
        }))
        
        # Navigate to the URL
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        
        # Wait for the page to load
        await page.wait_for_timeout(10000)
        
        # Click Trades tab
        trades_tab = await page.query_selector("text=Trades")
        if trades_tab:
            await trades_tab.click()
            await page.wait_for_timeout(5000)
        
        # Check for trade map related API calls
        trade_requests = [r for r in requests if 'trade' in r['url'].lower() or 'map' in r['url'].lower()]
        print(f"Trade/Map requests: {len(trade_requests)}")
        for r in trade_requests:
            print(f"  {r['method']} {r['url']}")
        
        # Check all API responses
        api_responses = [r for r in responses if r['url'].startswith('http://127.0.0.1:8088/api')]
        print(f"\nAPI responses: {len(api_responses)}")
        for r in api_responses:
            print(f"  {r['status']} {r['url']}")
        
        # Look at the trade map data loading
        # The trade map likely loads data via API - let's check
        tm_data = await page.evaluate("""() => {
            // Check if there's trade data in the global scope
            return {
                tradesData: window.tradesData || window._tradesData,
                tlData: window._tlData,
                activePair: document.querySelector('.tl-pair')?.value,
            };
        }""")
        print(f"\nTrade map data: {tm_data}")
        
        # Check what the canvas renders - try to get the trade map render function
        canvas_info = await page.evaluate("""() => {
            const canvases = document.querySelectorAll('canvas');
            const results = [];
            canvases.forEach((c, i) => {
                const ctx = c.getContext('2d');
                if (ctx) {
                    const imgData = ctx.getImageData(0, 0, c.width, c.height);
                    // Check if canvas has content (non-transparent pixels)
                    let hasContent = false;
                    for (let j = 0; j < imgData.data.length; j += 4) {
                        if (imgData.data[j+3] > 0) { hasContent = true; break; }
                    }
                    results.push({
                        index: i,
                        width: c.width,
                        height: c.height,
                        hasContent: hasContent,
                        className: c.className,
                    });
                }
            });
            return results;
        }""")
        print(f"\nCanvas details: {canvas_info}")
        
        # Try to trigger a redraw by changing pair
        tl_pair = await page.query_selector(".tl-pair")
        if tl_pair:
            await tl_pair.select_option("ETH/USDC")
            await page.wait_for_timeout(3000)
            await page.screenshot(path="dashboard_eth.png", full_page=True)
            print("Switched to ETH/USDC")
        
        await browser.close()

asyncio.run(main())
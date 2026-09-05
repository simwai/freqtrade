import asyncio
from playwright.async_api import async_playwright
import json

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Navigate to the URL
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        
        # Wait for the page to load
        await page.wait_for_timeout(10000)
        
        # Click Trades tab
        trades_tab = await page.query_selector("text=Trades")
        if trades_tab:
            await trades_tab.click()
            await page.wait_for_timeout(5000)
        
        # Now let's examine the trade map rendering code by looking at the JS functions
        trade_map_info = await page.evaluate("""() => {
            // Find the trade map mount function
            const results = {
                mountTradeMap: typeof mountTradeMap,
                tlTab: typeof _tmTab,
                tlDetail: typeof _tmDetail,
                tlPairValue: document.querySelector('.tl-pair')?.value,
                tlMarkSelValue: document.querySelector('.tl-mark-sel')?.value,
                tlMarkerSelValue: document.querySelector('.tl-marker-sel')?.value,
                tlCandleSelValue: document.querySelector('.tl-candle-sel')?.value,
                tlExitSelValue: document.querySelector('.tl-exit-sel')?.value,
            };
            
            // Check for any global trade map objects
            for (const key of Object.keys(window)) {
                if (key.toLowerCase().includes('trade') || key.toLowerCase().includes('map') || key.toLowerCase().includes('tl')) {
                    results[key] = typeof window[key];
                }
            }
            
            return results;
        }""")
        print(f"Trade map info: {json.dumps(trade_map_info, indent=2)}")
        
        # Let's try to call the render function manually or inspect the canvas drawing
        # The canvas at index 2 is the trade map (y=750)
        canvas_data = await page.evaluate("""() => {
            const canvases = document.querySelectorAll('canvas');
            const c = canvases[2]; // trade map canvas
            const ctx = c.getContext('2d');
            const imgData = ctx.getImageData(0, 0, c.width, c.height);
            
            // Sample some pixels to understand the rendering
            const samples = [];
            for (let y = 0; y < c.height; y += 50) {
                for (let x = 0; x < c.width; x += 100) {
                    const idx = (y * c.width + x) * 4;
                    if (imgData.data[idx + 3] > 0) {
                        samples.push({
                            x, y,
                            r: imgData.data[idx],
                            g: imgData.data[idx + 1],
                            b: imgData.data[idx + 2],
                            a: imgData.data[idx + 3]
                        });
                    }
                }
            }
            return {
                width: c.width,
                height: c.height,
                nonTransparentPixels: samples.length,
                samples: samples.slice(0, 50)
            };
        }""")
        print(f"\nCanvas analysis: {json.dumps(canvas_data, indent=2)}")
        
        # Now let's look at the actual trade map rendering by evaluating the JS
        # Try to get the trade data and see how it's mapped to canvas coordinates
        trade_debug = await page.evaluate("""() => {
            // Check if there's a way to access the trade map data
            // Look for the trades data in the global scope or in the component
            const pair = document.querySelector('.tl-pair')?.value;
            console.log('Current pair:', pair);
            
            // Check for any data loading functions
            return {
                pair: pair,
                // Check if there's a render function we can call
                hasRenderTradeMap: typeof renderTradeMap !== 'undefined',
                hasDrawTradeMap: typeof drawTradeMap !== 'undefined',
            };
        }""")
        print(f"\nTrade debug: {json.dumps(trade_debug, indent=2)}")
        
        # Let's try to understand the coordinate mapping
        # The trade map shows trades as lines from entry to exit
        # Let's check the first few trades and their times vs candle times
        coord_check = await page.evaluate("""() => {
            // Get the first trade times
            const pair = document.querySelector('.tl-pair')?.value;
            // The trade data should be loaded - check if it's in a global var
            // Let's check the network response data
            return { pair };
        }""")
        print(f"\nCoord check: {json.dumps(coord_check, indent=2)}")
        
        await browser.close()

asyncio.run(main())
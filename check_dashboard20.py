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
        
        # Navigate to the URL with strategy parameter
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        
        # Wait for the page to load
        await page.wait_for_timeout(10000)
        
        # Check the openStrategy function
        open_strategy = await page.evaluate("""() => {
            if (typeof openStrategy === 'function') {
                return openStrategy.toString();
            }
            return 'not found';
        }""")
        print(f"openStrategy source (first 8000 chars): {open_strategy[:8000]}")
        
        # Check the populateTradeRunSelect function to see how it gets trade runs
        populate_runs = await page.evaluate("""() => {
            if (typeof populateTradeRunSelect === 'function') {
                return populateTradeRunSelect.toString();
            }
            return 'not found';
        }""")
        print(f"\npopulateTradeRunSelect source: {populate_runs}")
        
        # Check how LAB.trade_runs gets populated
        lab_check = await page.evaluate("""() => {
            return {
                LAB: window.LAB ? {
                    trade_runs: window.LAB.trade_runs?.length,
                    backtests: window.LAB.backtests?.length,
                    benchmarks: window.LAB.benchmarks?.length,
                } : null,
            };
        }""")
        print(f"\nLAB check: {json.dumps(lab_check, indent=2)}")
        
        # Try calling openStrategy manually
        open_result = await page.evaluate("""() => {
            try {
                openStrategy('ScreenerDpoBbwpWick');
                return { success: true };
            } catch (e) {
                return { error: e.toString(), stack: e.stack };
            }
        }""")
        print(f"\nopenStrategy result: {json.dumps(open_result, indent=2)}")
        
        # Wait for async operations
        await page.wait_for_timeout(5000)
        
        # Check state after openStrategy
        state = await page.evaluate("""() => {
            return {
                LAB_trade_runs: window.LAB?.trade_runs?.length || 0,
                _tmTab: !!window._tmTab,
                _tmDetail: !!window._tmDetail,
                tradeRunSelect: document.getElementById('tradeRun')?.value,
            };
        }""")
        print(f"\nState after openStrategy: {json.dumps(state, indent=2)}")
        
        await browser.close()

asyncio.run(main())
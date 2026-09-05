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
        
        # Let's examine the loadTradeRun function and related functions
        debug_info = await page.evaluate("""() => {
            // Get the function source for loadTradeRun
            const results = {};
            
            // Check the run select value
            const runSelect = document.querySelector('.tl-run-select') || document.querySelector('[class*="run"] select');
            results.runSelect = runSelect ? runSelect.value : 'not found';
            
            // Check what populateTradeRunSelect does
            if (typeof populateTradeRunSelect === 'function') {
                try {
                    populateTradeRunSelect();
                    results.populateResult = 'called';
                } catch (e) {
                    results.populateError = e.toString();
                }
            }
            
            // Check the current strategy
            results.strategy = document.querySelector('[class*="strategy"]')?.textContent || 'unknown';
            
            // Check for the run data in localStorage or sessionStorage
            try {
                results.localStorage = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key && (key.includes('trade') || key.includes('run') || key.includes('hist'))) {
                        results.localStorage[key] = localStorage.getItem(key);
                    }
                }
            } catch (e) {
                results.localStorageError = e.toString();
            }
            
            return results;
        }""")
        print(f"Debug info: {json.dumps(debug_info, indent=2)}")
        
        # Let's check the populateTradeRunSelect function source
        func_source = await page.evaluate("""() => {
            if (typeof populateTradeRunSelect === 'function') {
                return populateTradeRunSelect.toString();
            }
            return 'not found';
        }""")
        print(f"\npopulateTradeRunSelect source (first 3000 chars): {func_source[:3000]}")
        
        # Check loadTradeRun function source
        load_source = await page.evaluate("""() => {
            if (typeof loadTradeRun === 'function') {
                return loadTradeRun.toString();
            }
            return 'not found';
        }""")
        print(f"\nloadTradeRun source (first 5000 chars): {load_source[:5000]}")
        
        # Check tlRender function source
        render_source = await page.evaluate("""() => {
            if (typeof tlRender === 'function') {
                return tlRender.toString();
            }
            return 'not found';
        }""")
        print(f"\ntlRender source (first 5000 chars): {render_source[:5000]}")
        
        await browser.close()

asyncio.run(main())
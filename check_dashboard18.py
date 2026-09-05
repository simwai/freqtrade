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
        
        # Check what the initialization does
        init_check = await page.evaluate("""() => {
            // Check the URL hash
            const hash = window.location.hash;
            console.log('Hash:', hash);
            
            // Check if there's a strategy in the hash
            const params = new URLSearchParams(hash.slice(1));
            const strategy = params.get('s');
            console.log('Strategy from hash:', strategy);
            
            // Check LAB object
            return {
                hash: hash,
                strategyParam: strategy,
                LAB: window.LAB ? {
                    trade_runs: window.LAB.trade_runs?.length,
                    current_strategy: window.LAB.current_strategy,
                } : null,
                _tmTab: !!window._tmTab,
                _tmDetail: !!window._tmDetail,
            };
        }""")
        print(f"Init check: {json.dumps(init_check, indent=2)}")
        
        # Check the renderLab function which should handle strategy selection
        render_lab = await page.evaluate("""() => {
            if (typeof renderLab === 'function') {
                return renderLab.toString();
            }
            return 'not found';
        }""")
        print(f"\nrenderLab source (first 5000 chars): {render_lab[:5000]}")
        
        # Check the tlSetRun function to see how it gets timeframe and mode
        # The issue might be that the runRow is not found in LAB.backtests or LAB.benchmarks
        backtest_check = await page.evaluate("""() => {
            const data = {
                strategy: "ScreenerDpoBbwpWick",
                source: "backtest-result-2026-09-03_14-51-57.zip"
            };
            const runRow = (LAB.backtests || []).find(r => r.strategy === data.strategy && r.source === data.source)
                || (LAB.benchmarks || []).find(r => r.strategy === data.strategy && r.source === data.source);
            return {
                backtestsCount: LAB.backtests?.length || 0,
                benchmarksCount: LAB.benchmarks?.length || 0,
                runRowFound: !!runRow,
                runRow: runRow ? { timeframe: runRow.timeframe, trading_mode: runRow.trading_mode } : null,
            };
        }""")
        print(f"\nBacktest check: {json.dumps(backtest_check, indent=2)}")
        
        await browser.close()

asyncio.run(main())
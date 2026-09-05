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
        
        # Check the tlSetRun function
        tlsetrun_source = await page.evaluate("""() => {
            if (typeof tlSetRun === 'function') {
                return tlSetRun.toString();
            }
            return 'not found';
        }""")
        print(f"tlSetRun source (first 8000 chars): {tlsetrun_source[:8000]}")
        
        # Check the _tlInstances
        instances = await page.evaluate("""() => {
            return {
                _tlInstances: window._tlInstances,
                _tmTab: window._tmTab,
                _tmDetail: window._tmDetail,
            };
        }""")
        print(f"\nInstances: {json.dumps(instances, indent=2, default=str)}")
        
        # Check if the mountTradeMap was called for tm-tab
        tm_tab_el = await page.query_selector("#tm-tab")
        if tm_tab_el:
            html = await tm_tab_el.inner_html()
            print(f"\ntm-tab has content: {len(html) > 100}")
            # Check if it has the chart element
            chart_el = await tm_tab_el.query_selector(".tl-chart")
            print(f"  Has .tl-chart: {chart_el is not None}")
        
        # Try to manually create the trade map instance and load data
        manual_result = await page.evaluate("""() => {
            try {
                // First, ensure the mount exists
                if (!window._tmTab) {
                    window._tmTab = mountTradeMap('tm-tab');
                    console.log('Created _tmTab:', window._tmTab);
                }
                
                // Now load the trade data
                const key = "ScreenerDpoBbwpWick__2026-09-03_14-51-57";
                const sel = $('tradeRun');
                if (sel) sel.value = key;
                
                return loadTradeRun();
            } catch (e) {
                return { error: e.toString(), stack: e.stack };
            }
        }""")
        print(f"\nManual load result: {json.dumps(manual_result, indent=2, default=str)}")
        
        # Wait for fetch
        await page.wait_for_timeout(5000)
        
        # Check state after load
        state = await page.evaluate("""() => {
            return {
                _tmTab: window._tmTab,
                tradeCache: window.tradeCache,
                _renderedTradeData: window._renderedTradeData,
            };
        }""")
        print(f"\nState after manual load: {json.dumps(state, indent=2, default=str)}")
        
        # Try to render
        if state.get('_tmTab'):
            render_result = await page.evaluate("""() => {
                try {
                    return tlRender(window._tmTab);
                } catch (e) {
                    return { error: e.toString(), stack: e.stack };
                }
            }""")
            print(f"\nRender result: {json.dumps(render_result, indent=2, default=str)}")
        
        await browser.close()

asyncio.run(main())
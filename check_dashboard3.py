import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Listen for console messages
        page.on("console", lambda msg: print(f"CONSOLE [{msg.type}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"PAGE ERROR: {err}"))
        
        # Navigate to the URL
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        
        # Wait for the page to load
        await page.wait_for_timeout(10000)
        
        # Take a screenshot
        await page.screenshot(path="dashboard_screenshot2.png", full_page=True)
        
        # Find the Trade map element and click to see it
        # The Trade map is in the "Trades" tab - let's check if we need to click it
        trades_tab = await page.query_selector("text=Trades")
        if trades_tab:
            print("Found Trades tab, clicking...")
            await trades_tab.click()
            await page.wait_for_timeout(3000)
            await page.screenshot(path="dashboard_trades_tab.png", full_page=True)
        
        # Check the tm-tab and tm-detail elements
        tm_tab = await page.query_selector("#tm-tab")
        tm_detail = await page.query_selector("#tm-detail")
        
        if tm_tab:
            box = await tm_tab.bounding_box()
            print(f"tm-tab: {box}")
            html = await tm_tab.inner_html()
            print(f"tm-tab HTML (first 2000): {html[:2000]}")
        
        if tm_detail:
            box = await tm_detail.bounding_box()
            print(f"tm-detail: {box}")
            html = await tm_detail.inner_html()
            print(f"tm-detail HTML (first 2000): {html[:2000]}")
        
        # Check the pair selector in the trade map
        tl_pair = await page.query_selector(".tl-pair")
        if tl_pair:
            print("Found tl-pair selector")
            options = await tl_pair.query_selector_all("option")
            print(f"  Options: {len(options)}")
            for opt in options[:10]:
                text = await opt.inner_text()
                value = await opt.get_attribute("value")
                print(f"    {value}: {text}")
        
        # Execute JS to check the trade map internal state
        tm_state = await page.evaluate("""() => {
            return {
                tmTab: window._tmTab,
                tmDetail: window._tmDetail,
                tlPair: document.querySelector('.tl-pair')?.value,
            };
        }""")
        print(f"\nTrade map state: {tm_state}")
        
        # Check the canvas for the trade map
        canvases = await page.query_selector_all("canvas")
        for i, canvas in enumerate(canvases):
            box = await canvas.bounding_box()
            if box and box['width'] > 500:
                print(f"\nLarge canvas {i}: {box}")
                # Try to get canvas data
                data_url = await page.evaluate(f"""() => {{
                    const c = document.querySelectorAll('canvas')[{i}];
                    return c.toDataURL('image/png');
                }}""")
                print(f"  Canvas data URL length: {len(data_url)}")
        
        await browser.close()

asyncio.run(main())
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Navigate to the URL
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        
        # Wait for the page to load
        await page.wait_for_timeout(10000)
        
        # Take a screenshot
        await page.screenshot(path="dashboard_screenshot.png", full_page=True)
        
        # Get all chart/canvas elements details
        canvases = await page.query_selector_all("canvas")
        print(f"Found {len(canvases)} canvas elements")
        for i, canvas in enumerate(canvases):
            box = await canvas.bounding_box()
            print(f"  Canvas {i}: {box}")
            # Try to get canvas context/type
            class_name = await canvas.get_attribute("class")
            print(f"    class: {class_name}")
        
        # Check for any chart-related elements with more detail
        charts = await page.query_selector_all("[class*='chart' i], [class*='Chart' i], [id*='chart' i], [id*='Chart' i]")
        print(f"\nFound {len(charts)} chart elements")
        for i, chart in enumerate(charts[:10]):
            tag = await chart.evaluate("el => el.tagName")
            class_name = await chart.get_attribute("class")
            id_name = await chart.get_attribute("id")
            box = await chart.bounding_box()
            print(f"  Chart {i}: <{tag}> class={class_name} id={id_name} box={box}")
        
        # Look for trade map / strategy map related elements
        trade_map = await page.query_selector_all("[class*='trade' i], [class*='map' i], [class*='Map' i]")
        print(f"\nFound {len(trade_map)} trade/map elements")
        for i, elem in enumerate(trade_map[:20]):
            tag = await elem.evaluate("el => el.tagName")
            class_name = await elem.get_attribute("class")
            id_name = await elem.get_attribute("id")
            box = await elem.bounding_box()
            if box and (box['width'] > 100 or box['height'] > 100):
                print(f"  Element {i}: <{tag}> class={class_name} id={id_name} box={box}")
        
        # Check for any specific "trade map" or "strategy lab" component
        # Look at the HTML structure
        html = await page.content()
        
        # Search for specific terms in HTML
        import re
        for term in ['trade-map', 'trademap', 'trade_map', 'strategy-map', 'strategymap', 'tradeTrack', 'trade-track', 'marker', 'Marker']:
            matches = [(m.start(), html[max(0,m.start()-100):m.start()+200]) for m in re.finditer(term, html, re.IGNORECASE)]
            if matches:
                print(f"\n=== Found '{term}' ({len(matches)} matches) ===")
                for pos, context in matches[:3]:
                    print(f"  Pos {pos}: ...{context}...")
        
        await browser.close()

asyncio.run(main())
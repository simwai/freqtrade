import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Navigate to the URL
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        
        # Wait for the page to load
        await page.wait_for_timeout(5000)
        
        # Take a screenshot
        await page.screenshot(path="dashboard_screenshot.png", full_page=True)
        
        # Get page content
        content = await page.content()
        print("Page loaded successfully")
        
        # Try to find the chart/canvas elements
        canvases = await page.query_selector_all("canvas")
        print(f"Found {len(canvases)} canvas elements")
        
        # Try to find any SVG elements
        svgs = await page.query_selector_all("svg")
        print(f"Found {len(svgs)} SVG elements")
        
        # Check for Plotly charts
        plotly_divs = await page.query_selector_all(".plotly-graph-div, [data-plotly]")
        print(f"Found {len(plotly_divs)} Plotly elements")
        
        # Check for any chart-related elements
        charts = await page.query_selector_all(".chart, [class*='chart'], [class*='Chart']")
        print(f"Found {len(charts)} chart elements")
        
        # Print all visible text on the page for debugging
        body_text = await page.inner_text("body")
        print(f"Body text (first 2000 chars): {body_text[:2000]}")
        
        await browser.close()

asyncio.run(main())
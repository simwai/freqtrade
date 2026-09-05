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
        
        # Check the loadConfigs function
        load_configs = await page.evaluate("""() => {
            if (typeof loadConfigs === 'function') {
                return loadConfigs.toString();
            }
            return 'not found';
        }""")
        print(f"loadConfigs source (first 8000 chars): {load_configs[:8000]}")
        
        # Check the init function that runs on page load
        init_check = await page.evaluate("""() => {
            // Check for any initialization functions
            return {
                initLab: typeof initLab,
                renderDashboard: typeof renderDashboard,
                loadLosses: typeof loadLosses,
            };
        }""")
        print(f"\nInit functions: {json.dumps(init_check, indent=2)}")
        
        # Check the renderDashboard function
        render_dashboard = await page.evaluate("""() => {
            if (typeof renderDashboard === 'function') {
                return renderDashboard.toString();
            }
            return 'not found';
        }""")
        print(f"\nrenderDashboard source (first 8000 chars): {render_dashboard[:8000]}")
        
        await browser.close()

asyncio.run(main())
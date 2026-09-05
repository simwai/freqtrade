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
        
        # Check the loadLosses function
        load_losses = await page.evaluate("""() => {
            if (typeof loadLosses === 'function') {
                return loadLosses.toString();
            }
            return 'not found';
        }""")
        print(f"loadLosses source (first 8000 chars): {load_losses[:8000]}")
        
        # Check the visibleCanonical function
        visible_canonical = await page.evaluate("""() => {
            if (typeof visibleCanonical === 'function') {
                return visibleCanonical.toString();
            }
            return 'not found';
        }""")
        print(f"\nvisibleCanonical source (first 5000 chars): {visible_canonical[:5000]}")
        
        # Check the state object
        state_obj = await page.evaluate("""() => {
            return {
                state: window.state,
                LAB: window.LAB,
            };
        }""")
        print(f"\nState object: {json.dumps(state_obj, indent=2, default=str)}")
        
        await browser.close()

asyncio.run(main())
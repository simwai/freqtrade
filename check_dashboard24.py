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
        
        # Get the page HTML to see initialization scripts
        html = await page.content()
        
        # Find script tags
        import re
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
        for i, script in enumerate(scripts):
            if 'LAB' in script or 'init' in script.lower() or 'state' in script.lower():
                print(f"\nScript {i} (first 3000 chars):")
                print(script[:3000])
        
        # Check for any global initialization function
        init_funcs = await page.evaluate("""() => {
            const funcs = [];
            for (const key of Object.keys(window)) {
                if (typeof window[key] === 'function' && 
                    (key.includes('init') || key.includes('Init') || key.includes('load') || key.includes('Load'))) {
                    funcs.push(key);
                }
            }
            return funcs;
        }""")
        print(f"\nInit functions: {json.dumps(init_funcs, indent=2)}")
        
        // Check the updateRunFields function
        update_run = await page.evaluate("""() => {
            if (typeof updateRunFields === 'function') {
                return updateRunFields.toString();
            }
            return 'not found';
        }""")
        print(f"\nupdateRunFields source: {update_run[:5000]}")
        
        // Check the defaultRunRange function
        default_range = await page.evaluate("""() => {
            if (typeof defaultRunRange === 'function') {
                return defaultRunRange.toString();
            }
            return 'not found';
        }""")
        print(f"\ndefaultRunRange source: {default_range[:5000]}")
        
        await browser.close()

asyncio.run(main())
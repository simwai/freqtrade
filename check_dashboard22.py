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
        
        # Check for initialization code in the global scope
        init_code = await page.evaluate("""() => {
            // Look for any code that initializes LAB
            const scripts = document.querySelectorAll('script');
            let initCode = '';
            scripts.forEach(s => {
                if (s.textContent && s.textContent.includes('LAB')) {
                    initCode += s.textContent.slice(0, 2000) + '\n---\n';
                }
            });
            return initCode;
        }""")
        print(f"Init code from scripts: {init_code[:5000]}")
        
        # Check the tlPresetInit function
        tl_preset = await page.evaluate("""() => {
            if (typeof tlPresetInit === 'function') {
                return tlPresetInit.toString();
            }
            return 'not found';
        }""")
        print(f"\ntlPresetInit source: {tl_preset[:5000]}")
        
        # Check the tlIndPopulateSelects function
        tl_ind = await page.evaluate("""() => {
            if (typeof tlIndPopulateSelects === 'function') {
                return tlIndPopulateSelects.toString();
            }
            return 'not found';
        }""")
        print(f"\ntlIndPopulateSelects source: {tl_ind[:5000]}")
        
        # Check the renderLab function to see if it initializes LAB
        render_lab = await page.evaluate("""() => {
            if (typeof renderLab === 'function') {
                return renderLab.toString();
            }
            return 'not found';
        }""")
        print(f"\nrenderLab source (full): {render_lab}")
        
        await browser.close()

asyncio.run(main())
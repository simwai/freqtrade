import asyncio
from playwright.async_api import async_playwright
import json

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        await page.wait_for_timeout(12000)
        
        print("Errors:", errors if errors else "none")
        
        # Use module-scope access
        tm = await page.evaluate("""() => {
            return {
                tmTabDefined: typeof _tmTab !== 'undefined',
                tmTabTrades: typeof _tmTab !== 'undefined' ? _tmTab.trades?.length : null,
                tmDetailDefined: typeof _tmDetail !== 'undefined',
            };
        }""")
        print(f"TradeMap module state: {json.dumps(tm)}")
        
        # Check canvas rendering
        canvas = await page.evaluate("""() => {
            const canvases = document.querySelectorAll('canvas');
            let results = [];
            canvases.forEach((c, i) => {
                if (c.width > 100) {
                    const ctx = c.getContext('2d');
                    try {
                        const d = ctx.getImageData(0, 0, c.width, c.height).data;
                        let n = 0;
                        for (let j = 3; j < d.length; j += 400) { if (d[j] > 0) n++; }
                        results.push({ i, w: c.width, h: c.height, painted: n });
                    } catch (e) { results.push({ i, error: String(e) }); }
                }
            });
            return results;
        }""")
        print(f"Canvases: {json.dumps(canvas, indent=2)}")
        
        await page.screenshot(path="final_test.png", full_page=True)
        await browser.close()

asyncio.run(main())
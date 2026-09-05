import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Capture console messages
        page.on("console", lambda msg: print(f"CONSOLE [{msg.type}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"PAGE ERROR: {err}"))
        
        # Navigate to the URL with strategy parameter
        await page.goto("http://127.0.0.1:8088/#s=ScreenerDpoBbwpWick", wait_until="networkidle")
        
        # Wait for the page to load and fix to execute
        await page.wait_for_timeout(15000)
        
        # Check if strategy detail view is open
        detail_check = await page.evaluate("""() => {
            return {
                detailActive: document.querySelector('#strategy-detail')?.classList.contains('active'),
                mainHidden: document.querySelector('#mainContent')?.classList.contains('hidden'),
                LAB: window.LAB ? {
                    canonical: window.LAB.canonical?.length,
                    trade_runs: window.LAB.trade_runs?.length,
                } : null,
                tmTab: !!window._tmTab,
            };
        }""")
        print(f"Detail check: {detail_check}")
        
        # Check if Trades tab was clicked
        trades_check = await page.evaluate("""() => {
            const tradesTab = Array.from(document.querySelectorAll('button, a, [role="tab"]'))
                .find(el => el.textContent.trim() === 'Trades');
            return {
                tradesTabExists: !!tradesTab,
                tradesTabClicked: tradesTab ? tradesTab.classList.contains('active') : false,
            };
        }""")
        print(f"Trades check: {trades_check}")
        
        // Check trade map canvas
        canvas_data = await page.evaluate("""() => {
            const canvases = document.querySelectorAll('canvas');
            const c = canvases[2]; // trade map canvas
            if (!c) return { error: 'No canvas found' };
            const ctx = c.getContext('2d');
            const imgData = ctx.getImageData(0, 0, c.width, c.height);
            let nonTransparent = 0;
            for (let y = 0; y < c.height; y += 20) {
                for (let x = 0; x < c.width; x += 50) {
                    const idx = (y * c.width + x) * 4;
                    if (imgData.data[idx + 3] > 0) nonTransparent++;
                }
            }
            return { width: c.width, height: c.height, nonTransparentPixels: nonTransparent };
        }""")
        print(f"Canvas: {canvas_data}")
        
        await page.screenshot(path="dashboard_fix_test.png", full_page=True)
        
        await browser.close()

asyncio.run(main())
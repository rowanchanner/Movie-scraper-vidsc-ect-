"""
Debug script: dumps ALL network requests from a provider embed page
to see what URLs are being loaded and find stream URLs.
"""
import asyncio
import sys
import os
import re

# Add project root to sys.path so scripts in tools/ can import scraper / server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def debug_provider(url):
    from playwright.async_api import async_playwright

    print(f"[DEBUG] Loading: {url}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        all_requests = []

        def on_request(req):
            all_requests.append(req.url)
            url_lower = req.url.lower()
            if any(ext in url_lower for ext in [".m3u8", ".mpd", ".mp4", ".ts", "playlist", "manifest", "stream"]):
                print(f"  🎯 STREAM: {req.url}")

        def on_response(resp):
            ct = resp.headers.get("content-type", "")
            if "mpegurl" in ct or "dash" in ct or "video" in ct:
                print(f"  🎬 VIDEO RESPONSE: {resp.url} [{ct}]")

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            print(f"\n[DEBUG] Page loaded. Title: {await page.title()}")
            print(f"[DEBUG] URL after navigation: {page.url}\n")

            # Get page content length
            content = await page.content()
            print(f"[DEBUG] Page HTML length: {len(content)} chars")

            # Check for iframes
            frames = page.frames
            print(f"[DEBUG] Frames count: {len(frames)}")
            for i, frame in enumerate(frames):
                print(f"  Frame {i}: {frame.url}")

            # Wait for more network activity
            print("\n[DEBUG] Waiting 8s for network activity...\n")
            await asyncio.sleep(8)

            # Try clicking play buttons
            for selector in [".play-btn", "[class*='play']", "button", "video", "#player"]:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0 and await el.is_visible():
                        print(f"[DEBUG] Clicking: {selector}")
                        await el.click(timeout=3000)
                        await asyncio.sleep(3)
                except:
                    pass

            # Also try in sub-frames
            for i, frame in enumerate(frames[1:], 1):
                try:
                    for selector in [".play-btn", "[class*='play']", "button", "video"]:
                        el = frame.locator(selector).first
                        if await el.count() > 0:
                            print(f"[DEBUG] Clicking in frame {i}: {selector}")
                            await el.click(timeout=3000)
                            await asyncio.sleep(3)
                except:
                    pass

            print(f"\n[DEBUG] Total requests captured: {len(all_requests)}")
            print("\n[DEBUG] All requests:")
            for r in all_requests:
                print(f"  {r}")

        except Exception as e:
            print(f"[DEBUG] Error: {e}")
        finally:
            await browser.close()


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://vidsrc.to/embed/movie/550"
    asyncio.run(debug_provider(url))

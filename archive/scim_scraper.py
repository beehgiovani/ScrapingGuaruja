import sys
import os
import asyncio
import time
import random
import uuid
import re
import argparse
import json
import requests
from playwright.async_api import async_playwright

# Add src to path if needed (though it's already in src)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from data_normalizer import normalize_lot_data
    from tor_manager import TorManager
    from proxy_config import get_proxy_for_worker
except ImportError:
    # If running from root as 'python src/scim_scraper.py'
    sys.path.append(os.path.join(os.getcwd(), 'src'))
    from data_normalizer import normalize_lot_data
    from tor_manager import TorManager
    from proxy_config import get_proxy_for_worker

# OCR Instance (Lazy Load)
ocr_instance = None

def preload_ddddocr():
    global ocr_instance
    if ocr_instance is None:
        try:
            import ddddocr
            ocr_instance = ddddocr.DdddOcr(show_ad=False)
            print("✓ ddddocr loaded.")
        except Exception as e:
            print(f"Error loading ddddocr: {e}")

async def solve_captcha(page, img_selector):
    global ocr_instance
    if ocr_instance is None:
        preload_ddddocr()
    try:
        img_element = await page.wait_for_selector(img_selector, timeout=5000)
        img_bytes = await img_element.screenshot()
        captcha_text = ocr_instance.classification(img_bytes)
        return captcha_text
    except Exception as e:
        print(f"Captcha error: {e}")
        return ""

async def handle_captcha_flow(page, success_selector):
    max_attempts = 15
    for attempt in range(max_attempts):
        if await page.query_selector(success_selector):
            return True
        
        captcha_img = await page.query_selector('img[src*="digits"]')
        if captcha_img:
            captcha_text = await solve_captcha(page, 'img[src*="digits"]')
            if captcha_text:
                await page.fill('#DigitDigits', captcha_text)
                await page.click('input[type="submit"]')
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except: pass
                await asyncio.sleep(1)
            else:
                await page.reload()
                await page.wait_for_load_state("networkidle")
        else:
            await asyncio.sleep(2)
    return await page.query_selector(success_selector) is not None

async def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--total', type=int, default=1)
    args, _ = parser.parse_known_args()

    preload_ddddocr()

    # Proxy/Tor Setup (Reusing automacao_imoveis.py logic)
    use_proxy = os.getenv("USE_PROXY_GLOBAL", "false").lower() == "true"
    tor = TorManager()
    use_tor = os.getenv("USE_TOR", "false").lower() == "true" and not use_proxy

    async with async_playwright() as p:
        launch_options = {
            'headless': os.getenv("HEADLESS_MODE", "true").lower() == "true"
        }
        
        if use_proxy:
            proxy_info = get_proxy_for_worker(args.shard)
            launch_options['proxy'] = {
                'server': f'{scheme}://{proxy_host_port}',
                'username': proxy_info.get('user', 'owoqoswg'),
                'password': os.environ.get('PROXY_PASS_WS', 'YOUR_PROXY_PASSWORD')
            }
        
        if use_tor:
            tor.start()
            # Standard Tor port used in the project
            launch_options['proxy'] = {
                'server': 'socks5://127.0.0.1:9152',
                'username': f'scim_{args.shard}_{int(time.time())}',
                'password': 'password'
            }

        browser = await p.firefox.launch(**launch_options)
        context = await browser.new_context(ignore_https_errors=True)
        # Increase timeouts for stability
        context.set_default_timeout(90000)
        page = await context.new_page()

        target_url = "https://scimpmgsp.geometrus.com.br/digits"
        print(f"Starting Scraper on {target_url}")
        
        try:
            await page.goto(target_url, timeout=120000)
        except Exception as e:
            print(f"Initial navigation failed: {e}. Retrying...")
            await page.reload()
            await page.goto(target_url, timeout=120000)

        success = await handle_captcha_flow(page, '#DigitIndexForm, #MctmLancamentoIdentificacao, .success, .error-message')
        
        if success:
            print("Successfully reached/passed digits page context!")
            content = await page.content()
            if "Dígitos" in content:
                 print("Still on digits page.")
            else:
                 print("Moved past digits page.")
        else:
            print("Failed to pass digits page.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())

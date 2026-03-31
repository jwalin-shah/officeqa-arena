#!/usr/bin/env python3
"""
Step 2: Dashboard discovery.

Launches Chrome with saved profile, navigates to the dashboard,
clicks the Dashboard tab, then:
  1. Dumps the full DOM text (to see what data is rendered)
  2. Intercepts network via CDP Network domain (catches what Playwright misses)
  3. Takes a screenshot
  4. Checks __NEXT_DATA__ for server-side data

Usage:
    python3 scripts/discover_dashboard_api.py
"""

import json
import subprocess
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE_DIR = Path(__file__).resolve().parent / "chrome_profile"
OUTPUT_DIR = Path(__file__).resolve().parent
DASHBOARD_URL = "https://arena.sentient.xyz/challenges/grounded-reasoning"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
REMOTE_DEBUG_PORT = 9222


def main():
    if not PROFILE_DIR.exists():
        print(f"ERROR: {PROFILE_DIR} not found. Run login_and_save_state.py first.")
        return

    print("Launching Chrome...")
    proc = subprocess.Popen([
        CHROME,
        f"--remote-debugging-port={REMOTE_DEBUG_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ])
    time.sleep(3)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{REMOTE_DEBUG_PORT}")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        # Enable CDP Network domain to capture all requests
        cdp = context.new_cdp_session(page)
        captured = []

        def on_response_received(params):
            url = params.get("response", {}).get("url", "")
            status = params.get("response", {}).get("status", 0)
            mime = params.get("response", {}).get("mimeType", "")
            req_id = params.get("requestId", "")
            captured.append({"url": url, "status": status, "mime": mime, "requestId": req_id})

        cdp.on("Network.responseReceived", on_response_received)
        cdp.send("Network.enable")

        # Navigate
        print(f"\nLoading {DASHBOARD_URL} ...")
        page.goto(DASHBOARD_URL, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Click Dashboard tab
        print("Looking for Dashboard tab...")
        clicked = False
        for selector in [
            "text=Dashboard",
            "button:has-text('Dashboard')",
            "a:has-text('Dashboard')",
            "[role='tab']:has-text('Dashboard')",
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    print(f"  Clicking: {selector}")
                    el.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            print("  Could not auto-click Dashboard. Listing buttons/tabs:")
            for sel in ["button", "a", "[role='tab']", "[role='tablist'] *"]:
                try:
                    texts = page.locator(sel).all_inner_texts()
                    if texts:
                        print(f"    {sel}: {[t.strip() for t in texts if t.strip()][:15]}")
                except Exception:
                    pass

        print("Waiting 15s for data to load...")
        page.wait_for_timeout(15000)

        # --- Collect data ---

        # 1. Screenshot
        ss_path = str(OUTPUT_DIR / "dashboard_screenshot.png")
        page.screenshot(path=ss_path, full_page=True)
        print(f"\nScreenshot: {ss_path}")

        # 2. Current URL
        print(f"Current URL: {page.url}")

        # 3. __NEXT_DATA__
        next_data = page.evaluate("""
            () => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent : null;
            }
        """)
        if next_data:
            nd_path = str(OUTPUT_DIR / "next_data.json")
            with open(nd_path, "w") as f:
                f.write(next_data)
            print(f"__NEXT_DATA__ saved to: {nd_path} ({len(next_data)} chars)")
            # Preview
            try:
                nd = json.loads(next_data)
                print(f"  Keys: {list(nd.keys())}")
                if "props" in nd:
                    print(f"  props keys: {list(nd['props'].keys())[:10]}")
            except Exception:
                pass

        # 4. Full page text
        body_text = page.locator("body").inner_text()
        text_path = str(OUTPUT_DIR / "dashboard_text.txt")
        with open(text_path, "w") as f:
            f.write(body_text)
        print(f"Page text saved to: {text_path} ({len(body_text)} chars)")
        # Show lines with numbers (likely data)
        print("\n--- Lines with numbers (likely submission data) ---")
        for line in body_text.split("\n"):
            line = line.strip()
            if line and any(c.isdigit() for c in line) and len(line) > 3:
                print(f"  {line}")

        # 5. CDP captured requests
        print(f"\n--- CDP captured {len(captured)} responses ---")
        for c in captured:
            url = c["url"]
            if any(url.endswith(ext) for ext in [".js", ".css", ".png", ".svg", ".ico", ".woff2", ".woff"]):
                continue
            if "chrome-extension" in url or "favicon" in url:
                continue
            print(f"  [{c['status']}] {c['mime'][:30]:30s} {url[:120]}")

            # Try to get response body via CDP
            try:
                body_result = cdp.send("Network.getResponseBody", {"requestId": c["requestId"]})
                body = body_result.get("body", "")
                if body and "text" in c["mime"]:
                    c["body"] = body[:3000]
                    if len(body) < 5000 and "html" not in c["mime"]:
                        print(f"    Body: {body[:300]}")
            except Exception:
                pass

        # Save CDP results
        cdp_path = str(OUTPUT_DIR / "cdp_responses.jsonl")
        with open(cdp_path, "w") as f:
            for c in captured:
                f.write(json.dumps(c) + "\n")
        print(f"\nCDP responses saved to: {cdp_path}")

        # 6. Check for iframes
        frames = page.frames
        if len(frames) > 1:
            print(f"\nFound {len(frames)} frames:")
            for fr in frames:
                print(f"  {fr.url}")

    proc.terminate()
    print("\nDone.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Step 1: One-time login capture.

Launches a real Chrome instance with a persistent user data dir
(not detectable as automation by Google OAuth). Log in manually,
then press Enter to save cookies for reuse.

Usage:
    python3 scripts/login_and_save_state.py
"""

import subprocess
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent / "sentient_storage_state.json"
PROFILE_DIR = Path(__file__).resolve().parent / "chrome_profile"
START_URL = "https://arena.sentient.xyz/challenges/grounded-reasoning"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
REMOTE_DEBUG_PORT = 9222


def main():
    PROFILE_DIR.mkdir(exist_ok=True)

    print("\n=== Sentient Arena Login ===")
    print("Launching Chrome with remote debugging...")
    print("(This is a real Chrome — Google OAuth will work.)\n")

    # Launch Chrome with remote debugging and a dedicated profile
    proc = subprocess.Popen([
        CHROME,
        f"--remote-debugging-port={REMOTE_DEBUG_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        START_URL,
    ])

    print(f"Chrome opened to: {START_URL}")
    print("1. Log in manually (Google OAuth should work fine).")
    print("2. Click into the Dashboard tab so your submission data is visible.")
    print("3. Come back here and press Enter.\n")
    input("Press Enter when logged in and dashboard is visible... ")

    # Now connect Playwright to the running Chrome to extract state
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{REMOTE_DEBUG_PORT}")
        context = browser.contexts[0]
        context.storage_state(path=str(STATE_FILE))
        print(f"\nSession saved to: {STATE_FILE}")
        # Don't close — let the user close Chrome themselves

    proc.terminate()
    print("Done. Chrome closed.")


if __name__ == "__main__":
    main()

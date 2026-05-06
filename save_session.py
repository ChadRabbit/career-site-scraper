"""
Save Session Script for LinkedIn Job Scraping

This script:
1. Launches a Chromium browser with a persistent context, allowing you to save your login session.
2. Prompts you to broswse manually and then press Enter to continue.

Author: Saransh Mehra
"""

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir="user_data",
        headless=False
    )
    page = context.new_page()
    page.goto("https://www.google.com")

    input("Browse manually, then press Enter...")

"""Read-only browser reconnaissance before the full workflow test."""
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'/'qa';OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,channel='chrome')
    page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
    page.goto('http://127.0.0.1:3000');page.wait_for_load_state('networkidle');page.screenshot(path=str(OUT/'landing-desktop.png'),full_page=True);page.screenshot(path=str(OUT/'landing-preview.png'))
    print({'title':page.title(),'buttons':page.get_by_role('button').all_text_contents(),'overflow':page.evaluate('document.documentElement.scrollWidth > innerWidth')})
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'landing-mobile.png'),full_page=True)
    print({'mobile_overflow':page.evaluate('document.documentElement.scrollWidth > innerWidth')})
    browser.close()

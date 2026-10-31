"""Verify the landing interactions and capture the three portable README images.

Run both app services and prepare a sample analysis/replay before running this.
This check reads existing data; it does not create or change workspace records.
"""
import json
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / 'output' / 'qa'
IMAGES = ROOT / 'docs' / 'images'
QA.mkdir(parents=True, exist_ok=True)
IMAGES.mkdir(parents=True, exist_ok=True)
BASE = 'http://127.0.0.1:3000'

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, channel='chrome')
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(BASE)
    page.wait_for_load_state('networkidle')
    page.evaluate('document.fonts.ready')
    checks = []

    for width in [1920, 1536, 1440, 1024, 768, 481, 480, 390, 320]:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.evaluate('window.scrollTo(0, 0)')
        expect(page.locator('.hero-actions .button')).to_be_visible()
        geometry = page.evaluate('''() => {
            const hero = document.querySelector('.hero').getBoundingClientRect();
            const actions = [...document.querySelector('.hero-actions').children]
                .map(el => el.getBoundingClientRect());
            const footnote = document.querySelector('.hero-footnote').getBoundingClientRect();
            const proof = document.querySelector('.proof-strip').getBoundingClientRect();
            return {overflow: document.documentElement.scrollWidth > innerWidth,
                contained: actions.every(r => r.top >= hero.top && r.bottom <= hero.bottom),
                footnoteContained: footnote.bottom <= hero.bottom,
                proofBelow: proof.top >= footnote.bottom,
                buttonClickable: actions.every(r => {
                    const el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                    return el && el.closest('.hero-actions');
                })};
        }''')
        assert not geometry['overflow'], (width, geometry)
        assert all(geometry[key] for key in ['contained', 'footnoteContained', 'proofBelow', 'buttonClickable']), (width, geometry)

        # Every marker must select its own explanation, fit its label, and close.
        for index, feature in enumerate(['Rotational speed', 'Process temperature', 'Torque']):
            button = page.locator('.hotspot').nth(index)
            if button.get_attribute('aria-expanded') == 'true':
                button.click()
            expect(button).to_have_attribute('aria-expanded', 'false')
            button.click()
            expect(button).to_have_attribute('aria-expanded', 'true')
            expect(page.locator('#machine-component-detail h3')).to_have_text(feature)
            expect(page.locator('.hotspot-callout')).to_have_count(1)
            bounds = page.evaluate('''() => {
                const image = document.querySelector('.machine-image').getBoundingClientRect();
                const label = document.querySelector('.hotspot-callout').getBoundingClientRect();
                return label.left >= image.left && label.right <= image.right
                    && label.top >= image.top && label.bottom <= image.bottom;
            }''')
            assert bounds, f'Clipped hotspot label at {width}px: {feature}'
            button.click()
            expect(button).to_have_attribute('aria-expanded', 'false')
            expect(page.locator('.hotspot-callout')).to_have_count(0)
        checks.append({'width': width, 'hero': 'passed', 'three_hotspots': 'passed'})

    # Native keyboard interaction must update the same selected/expanded state.
    page.locator('.hotspot').first.focus()
    page.keyboard.press('Enter')
    expect(page.locator('.hotspot').first).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('#machine-component-detail h3')).to_have_text('Rotational speed')
    page.keyboard.press('Space')
    expect(page.locator('.hotspot').first).to_have_attribute('aria-expanded', 'false')

    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.locator('.hotspot').first.click()
    page.locator('.machine-section').screenshot(path=str(QA / 'hotspot-fixed.png'))
    page.evaluate('window.scrollTo(0,0)')
    page.screenshot(path=str(IMAGES / 'landing-page.png'))
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(QA / 'hero-fixed-mobile.png'))

    page.set_viewport_size({'width': 1440, 'height': 1050})
    page.goto(BASE + '/dashboard')
    expect(page.get_by_text('Analyzed observations', exact=True)).to_be_visible(timeout=20000)
    expect(page.get_by_text('Operating conditions', exact=True)).to_be_visible()
    page.wait_for_timeout(800)  # Allow chart entrance animation to finish.
    page.screenshot(path=str(IMAGES / 'dashboard.png'))

    response = page.request.get(BASE + '/api/machines')
    assert response.ok, f'Machines API returned {response.status}'
    machines = response.json()
    replay = next((machine for machine in machines
                   if machine['id'].startswith('REPLAY-') and machine['reading_count'] >= 2), None)
    assert replay, 'Prepare a sample replay with at least two readings before capturing README images.'
    page.set_viewport_size({'width': 1440, 'height': 1400})
    page.goto(BASE + '/machines?machine=' + quote(replay['id'], safe=''))
    expect(page.locator('.machine-latest')).to_be_visible(timeout=20000)
    expect(page.get_by_role('heading', name='Recorded-data replay', exact=True)).to_be_visible()
    page.wait_for_timeout(800)
    page.screenshot(path=str(IMAGES / 'machines-replay.png'))

    assert not errors, errors
    print(json.dumps({'checks': checks, 'keyboard': 'passed', 'page_errors': errors,
                      'readme_images': [str(path.relative_to(ROOT)) for path in IMAGES.glob('*.png')]}, indent=2))
    browser.close()

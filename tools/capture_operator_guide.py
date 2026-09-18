"""Capture the real desktop forms in an isolated, stopped session for the guide.

Requires the desktop environment and Playwright with installed Edge. No capture,
OBS, renderer, or Discord actions are invoked. See doc/slides/README.md.
"""
import argparse
from pathlib import Path
import sys
import tempfile
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--playwright-path', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    if args.playwright_path:
        sys.path.insert(0, str(args.playwright_path))
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server
    from ddrcv.desktop.app import create_app
    from ddrcv.desktop.controller import Desk

    out = args.output or root / 'doc/slides/assets'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ddrcv-guide-') as temporary:
        desk = Desk(temporary)
        desk.draft['renderer']['path'] = 'C:/Games/ddr_score_render'
        desk.draft['results']['output_directory'] = 'C:/Games/ddrcv/screenshots'
        token = 'isolated-guide-session'
        server = make_server('127.0.0.1', 0, create_app(desk, token))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        errors = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1000, 'height': 900}, device_scale_factor=2)
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(
                    f'http://127.0.0.1:{server.server_port}/') else route.abort())
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                page.evaluate('''token => {
                  window.pywebview = {api: {session: async () => ({token}), pick: async () => null}};
                  window.dispatchEvent(new Event('pywebviewready'));
                }''', token)
                expect(page.locator('#phase')).to_have_text('Stopped')
                page.screenshot(path=str(out / 'panel.png'), full_page=True)
                page.locator('#panel-session section').nth(0).screenshot(path=str(out / 'status.png'))
                page.locator('#panel-session section').nth(1).screenshot(path=str(out / 'source.png'))
                source = page.locator('#panel-session section').nth(1).bounding_box()
                camera = page.locator('.camera-controls').bounding_box()
                page.screenshot(path=str(out / 'source-controls.png'), clip={
                    'x': source['x'], 'y': source['y'], 'width': source['width'],
                    'height': camera['y'] + camera['height'] - source['y'] + 12})
                page.locator('.session-grid').screenshot(path=str(out / 'score-readout.png'))
                page.locator('.session-bottom').screenshot(path=str(out / 'frame-health.png'))
                for tab in ['obs', 'renderer', 'results']:
                    page.locator(f'#tab-{tab}').click()
                    expect(page.locator(f'#panel-{tab}')).to_be_visible()
                    page.locator(f'#panel-{tab}').screenshot(path=str(out / f'{tab}.png'))
                page.locator('#panel-results section').nth(0).screenshot(path=str(out / 'discord.png'))
                discord_fields = page.locator('#panel-results section').nth(0).locator('.form-grid').bounding_box()
                discord_button = page.locator('#test-discord-webhook').bounding_box()
                page.screenshot(path=str(out / 'discord-controls.png'), clip={
                    'x': discord_fields['x'], 'y': discord_fields['y'], 'width': discord_fields['width'],
                    'height': discord_button['y'] + discord_button['height'] - discord_fields['y'] + 6})
                webhook_field = page.locator('[data-path="results.webhook"]').locator('..').bounding_box()
                page.screenshot(path=str(out / 'discord-webhook.png'), clip={
                    'x': webhook_field['x'], 'y': webhook_field['y'], 'width': webhook_field['width'],
                    'height': discord_button['y'] + discord_button['height'] - webhook_field['y'] + 6})
                page.locator('#panel-results section').nth(1).screenshot(path=str(out / 'results-capture.png'))
                assert desk.runtime is None, 'Guide capture must never start the runtime'
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
    print(f'Captured current UI images in {out}; no runtime or integrations started.')


if __name__ == '__main__':
    main()

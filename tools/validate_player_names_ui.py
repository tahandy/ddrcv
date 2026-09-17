"""Browser acceptance for name monitoring; real login replay plus UI edge cases.

Requires Playwright and Edge. Uses isolated local servers with no OBS, publisher,
or Discord connection. Desktop edge cases use intercepted status responses.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import json
import logging
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Also support the existing isolated browser-validation environment.
sys.path.append(str(ROOT / '.workbench/browser-tools'))


@contextmanager
def server(app):
    from werkzeug.serving import make_server
    http = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}'
    finally:
        http.shutdown()
        thread.join(timeout=2)
        http.server_close()


def main(video, output):
    from playwright.sync_api import sync_playwright, expect
    from ddrcv.desktop.app import create_app as desktop_app
    from ddrcv.desktop.controller import Desk
    from ddrcv.workbench.app import create_app as workbench_app
    from ddrcv.workbench.controller import Workbench

    output.mkdir(parents=True, exist_ok=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = root / 'workbench'
        settings.mkdir()
        (settings / 'settings.json').write_text(json.dumps({'player_names': {'enabled': True}}))
        wb = Workbench(settings, start_publisher=False)
        desk = Desk(root / 'desktop')
        try:
            with server(workbench_app(wb)) as url, server(desktop_app(desk, 'ui-test')) as desktop_url, sync_playwright() as pw:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1366, 'height': 900})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url)
                expect(page.locator('#p1-name')).to_have_text('—')
                wb.submit('open', kind='video', path=str(video.resolve()))
                wb.submit('seek', seconds=5)
                wb.submit('play')
                expect(page.locator('#p1-name')).to_have_text('ZVIDUN', timeout=15000)
                expect(page.locator('#p2-name')).to_have_text('EVILDAVE', timeout=15000)
                wb.submit('pause')
                expect(page.locator('#name-screen')).to_have_text('Login')
                expect(page.locator('#name-status')).to_have_text('Ready')
                actual = wb.status()
                page.screenshot(path=str(output / 'workbench-login.png'), full_page=True)
                # Async names are independent of frame delivery and its sequence.
                shown = deepcopy(actual)
                page.route('**/api/status', lambda route: route.fulfill(json=shown))
                sequence = shown['sequence']
                shown['published']['player_names'] = {'p1': '<b>PLAYER&1</b>', 'p2': None}
                expect(page.locator('#p1-name')).to_have_text('<b>PLAYER&1</b>')
                expect(page.locator('#p2-name')).to_have_text('—')
                assert page.locator('#p1-name b').count() == 0
                shown['player_name_status'].update(phase='failed', error='Test model unavailable', busy=False)
                expect(page.locator('#name-error')).to_have_text('Test model unavailable')
                expect(page.locator('#name-status')).to_have_text('OCR failed')
                shown['player_name_status'].update(phase='disabled', error=None)
                shown['published']['player_names'] = {'p1': None, 'p2': None}
                expect(page.locator('#p1-name')).to_have_text('—')
                expect(page.locator('#name-status')).to_have_text('Disabled')
                expect(page.locator('#name-error')).to_be_hidden()
                assert shown['sequence'] == sequence
                page.unroute('**/api/status')
                page.set_viewport_size({'width': 390, 'height': 844})
                expect(page.locator('#p1-name')).to_have_text('ZVIDUN')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / 'workbench-narrow.png'), full_page=True)
                wb.submit('seek', seconds=0)
                expect(page.locator('#p1-name')).to_have_text('—')
                expect(page.locator('#p2-name')).to_have_text('—')

                panel = browser.new_page(viewport={'width': 1120, 'height': 800})
                panel.on('pageerror', lambda error: errors.append(str(error)))
                status = desk.status()
                status['published'] = deepcopy(actual['published'])
                status['player_name_status'] = deepcopy(actual['player_name_status'])
                panel.route('**/api/status', lambda route: route.fulfill(json=status))
                panel.goto(desktop_url)
                panel.evaluate("""() => {
                    window.pywebview = {api: {session: async () => ({token: 'ui-test'})}};
                    window.dispatchEvent(new Event('pywebviewready'));
                }""")
                expect(panel.locator('#p1-name')).to_have_text('ZVIDUN')
                expect(panel.locator('#p2-name')).to_have_text('EVILDAVE')
                expect(panel.locator('#name-status')).to_have_text('Name recognition: Ready')
                enabled = panel.locator('[data-path="player_names.enabled"]')
                expect(enabled).not_to_be_checked()
                with panel.expect_response(lambda response: response.url.endswith('/api/config') and response.request.method == 'PUT') as saved:
                    enabled.check()
                assert saved.value.ok
                # The generic configuration binding must persist this exact option.
                assert desk.config()['draft']['player_names']['enabled'] is True
                panel.screenshot(path=str(output / 'desktop-status.png'), full_page=True)
                status['published']['player_names'] = {'p1': 'W' * 32, 'p2': '<b>NAME</b>'}
                expect(panel.locator('#p2-name')).to_have_text('<b>NAME</b>')
                assert panel.locator('#p2-name b').count() == 0
                panel.set_viewport_size({'width': 760, 'height': 560})
                assert panel.evaluate('document.documentElement.scrollWidth <= innerWidth')
                panel.screenshot(path=str(output / 'desktop-narrow.png'), full_page=True)
                status['published']['player_names'] = {'p1': None, 'p2': None}
                status['player_name_status'].update(phase='failed', error='Test model unavailable')
                expect(panel.locator('#p1-name')).to_have_text('—')
                expect(panel.locator('#p2-name')).to_have_text('—')
                expect(panel.locator('#name-status')).to_contain_text('OCR failed · Test model unavailable')
                status.pop('player_name_status')
                status['published'].pop('player_names')
                expect(panel.locator('#name-status')).to_have_text('Name recognition: Stopped')
                assert not errors, errors
                browser.close()
                report = {'names': actual['published']['player_names'],
                          'name_status': actual['player_name_status'], 'page_errors': errors,
                          'checks': ['real login replay', 'paused updates', 'partial names',
                                     'seek reset', 'error recovery', 'HTML escaping',
                                     'narrow layouts', 'desktop config persistence']}
                (output / 'report.json').write_text(json.dumps(report, indent=2))
                print(json.dumps(report, indent=2))
        finally:
            wb.close()
            desk.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, default=ROOT / 'apps/scripts/2025-03-19_16-47-45.mkv')
    parser.add_argument('--output', type=Path, default=ROOT / '.workbench/player-names-ui')
    args = parser.parse_args()
    main(args.video, args.output)

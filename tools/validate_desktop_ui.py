"""Headless dashboard acceptance against a real backend (requires Playwright).

Native bridge/file dialogs are stubbed here; validate_desktop_windows.py tests
actual WebView2 lifecycle separately. Only local video is accepted as input.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(video, out):
    from playwright.sync_api import sync_playwright, expect
    from ddrcv.apps.driver_config import load_config, write_json
    out.mkdir(parents=True, exist_ok=True)
    profile = out / 'profile.json'
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    write_json(profile, {'ingest': {'video': {'path': str(video.resolve())}},
                        'publish': {'websocket': {'port': port}},
                        'results': {'outbox_directory': str(out / 'outbox'), 'output_directory': str(out / 'screenshots')},
                        'score_filter': {'max_per_frame': None}})
    with (out / 'launcher.log').open('w') as log:
        backend = subprocess.Popen([sys.executable, '-B', '-m', 'ddrcv.desktop', '--no-panel',
                         '--data-dir', str(out / 'state'), '--config', str(profile)], cwd=ROOT, stdout=log, stderr=log)
    meta = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                meta = json.loads((out / 'state/instance.json').read_text())
                break
            except (OSError, ValueError):
                time.sleep(.1)
        if meta is None:
            raise RuntimeError('Backend did not start')
        errors, requests = [], []
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1120, 'height': 800})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: requests.append(r.url))
            def bridge():
                page.evaluate('token => {window.pywebview={api:{session:async()=>({token}),pick:async()=>null,close_ready:async()=>{window.probeClosed=true}}};window.dispatchEvent(new Event("pywebviewready"));}', meta['token'])
            page.goto(meta['url'])
            bridge()
            expect(page.locator('#phase')).to_have_text('Stopped')
            page.locator('#start').click()
            expect(page.locator('#phase')).to_have_text('Running', timeout=15000)
            expect(page.locator('#start')).to_be_disabled()
            expect(page.locator('#stop')).to_be_enabled()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(out / 'panel.png'), full_page=True)
            page.wait_for_timeout(1100)
            assert not [r for r in requests if '/api/frame' in r]
            page.locator('#snapshot').click()
            expect(page.locator('#preview')).to_be_visible()
            page.wait_for_function('document.getElementById("frame").naturalWidth===1280')
            assert len([r for r in requests if '/api/frame' in r]) == 1
            page.screenshot(path=str(out / 'snapshot.png'), full_page=True)
            page.set_viewport_size({'width': 760, 'height': 560})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(out / 'snapshot-minimum.png'), full_page=True)
            page.set_viewport_size({'width': 1120, 'height': 800})
            page.locator('#hide-preview').click()
            expect(page.locator('#panel-obs')).not_to_be_visible()
            expect(page.locator('#panel-renderer')).not_to_be_visible()
            page.locator('#tab-obs').click()
            expect(page.locator('#panel-session')).not_to_be_visible()
            expect(page.locator('#panel-obs')).to_be_visible()
            page.screenshot(path=str(out / 'obs.png'), full_page=True)
            page.locator('[data-path="obs.password"]').fill('desktop-ui-test-secret')
            page.wait_for_timeout(600)
            assert 'desktop-ui-test-secret' not in page.locator('#config-json').input_value()
            page.locator('#tab-renderer').click()
            expect(page.locator('#panel-obs')).not_to_be_visible()
            expect(page.locator('#panel-renderer')).to_be_visible()
            page.screenshot(path=str(out / 'renderer.png'), full_page=True)
            page.locator('#tab-results').click()
            expect(page.locator('#panel-results')).to_be_visible()
            expect(page.locator('#panel-renderer')).not_to_be_visible()
            expect(page.locator('#panel-results h2').first).to_contain_text('Discord')
            expect(page.locator('[data-path="results.enabled"]')).to_be_checked()
            filename_names = page.locator('[data-path="results.include_player_names"]')
            expect(filename_names).to_be_checked()
            filename_names.uncheck()
            export_folder = str(out / 'selected screenshots')
            page.evaluate('path => window.pywebview.api.pick = async () => path', export_folder)
            page.locator('#browse-results').click()
            expect(page.locator('[data-path="results.output_directory"]')).to_have_value(export_folder)
            names = page.locator('[data-path="results.parse_names"]')
            expect(names).to_be_checked()
            names.uncheck()
            webhook = page.locator('[data-path="results.webhook"]')
            webhook.fill('https://discord.com/api/webhooks/1/desktop-ui-test')
            discord = page.locator('[data-path="results.discord"]')
            discord.check()
            expect(page.locator('[data-path="results.enabled"]')).to_be_checked()
            # Exercise publishing controls without sending any external messages.
            discord.uncheck()
            page.locator('[data-path="results.enabled"]').uncheck()
            page.locator('#apply-results').click()
            expect(page.locator('#results-feedback')).to_have_text('Results settings applied')
            expect(page.locator('#phase')).to_have_text('Running')
            assert 'desktop-ui-test' not in page.locator('#config-json').input_value()
            page.screenshot(path=str(out / 'results.png'), full_page=True)
            page.reload()
            bridge()
            page.locator('#tab-results').click()
            expect(names).not_to_be_checked()
            expect(webhook).to_have_value('[unchanged secret]')
            expect(filename_names).not_to_be_checked()
            expect(page.locator('[data-path="results.output_directory"]')).to_have_value(export_folder)
            page.locator('#tab-results').press('ArrowLeft')
            expect(page.locator('#tab-renderer')).to_be_focused()
            page.locator('#tab-renderer').press('Home')
            expect(page.locator('#panel-session')).to_be_visible()
            expect(page.locator('#tab-session')).to_be_focused()
            page.locator('#tab-session').press('ArrowRight')
            expect(page.locator('#panel-obs')).to_be_visible()
            expect(page.locator('[data-path="obs.password"]')).not_to_have_value('')
            page.locator('#tab-session').click()
            expect(page.locator('#phase')).to_have_text('Running')
            saved = out / 'saved-profile.json'
            page.evaluate('path => window.pywebview.api.pick = async () => path', str(saved))
            page.locator('#save-as').click()
            expect(page.locator('#profile')).to_have_text(str(saved))
            assert load_config(saved)['obs']['password'] == 'desktop-ui-test-secret'
            assert load_config(saved)['results']['parse_names'] is False
            assert load_config(saved)['results']['webhook'].endswith('/desktop-ui-test')
            assert load_config(saved)['results']['output_directory'] == export_folder
            assert load_config(saved)['results']['include_player_names'] is False
            page.locator('[data-path="publish.websocket.port"]').fill(str(port + 1 if port < 65535 else port - 1))
            page.wait_for_timeout(600)
            expect(page.locator('#pending')).to_have_text('Draft changes · not applied')
            page.evaluate('window.deskClose()')
            page.wait_for_function('window.probeClosed===true')
            status = page.request.get(meta['url']+'/api/status', headers={'X-Desk-Token':meta['token']}).json()
            assert status['phase'] == 'Running' and status['publisher']['port'] == port
            page.reload()
            bridge()
            expect(page.locator('[data-path="publish.websocket.port"]')).not_to_have_value(str(port))
            page.evaluate('window.deskVisibility(false)')
            page.wait_for_timeout(500)
            count = len([r for r in requests if '/api/status' in r])
            page.wait_for_timeout(1000)
            assert len([r for r in requests if '/api/status' in r]) == count
            page.evaluate('window.deskVisibility(true)')
            page.wait_for_timeout(500)
            assert len([r for r in requests if '/api/status' in r]) > count
            # The real backend keeps replaying the file. Mock only the camera
            # action to exercise the failure UI without accessing event hardware.
            actions = []
            def camera_action(route):
                action = route.request.post_data_json['action']
                actions.append(action)
                if action == 'switch_source':
                    route.fulfill(status=400, json={'error': 'Test camera unavailable; current source retained'})
                else:
                    route.continue_()
            page.route('**/api/action', camera_action)
            page.locator('#source-kind').select_option('simple')
            page.locator('#camera-index').fill('2')
            expect(page.locator('#switch-source')).to_be_enabled()
            page.locator('#switch-source').click()
            expect(page.locator('#error')).to_have_text('Test camera unavailable; current source retained')
            expect(page.locator('#switch-source')).to_be_enabled()
            expect(page.locator('#phase')).to_have_text('Running')
            assert actions == ['switch_source'], actions
            cfg = page.request.get(meta['url']+'/api/config', headers={'X-Desk-Token':meta['token']}).json()
            assert cfg['draft']['ingest']['simple']['uri'] == 2
            status = page.request.get(meta['url']+'/api/status', headers={'X-Desk-Token':meta['token']}).json()
            assert 'video' in status['source'] and status['publisher']['port'] == port
            page.unroute('**/api/action', camera_action)
            # Presentation fixtures use the real page/JS, with status responses
            # replaced only for reproducible visual states. No capture is changed.
            from copy import deepcopy
            healthy = deepcopy(status)
            healthy.update(phase='Running', error=None, source_error=None, source_switching=False,
                           source={'simple': {'uri': 1}}, source_revision=10, pending=False,
                           published={'state': 'song_playing', 'players': [True, True],
                                      'score': {'p1_score': 198430, 'p2_score': 186250}},
                           raw_state='song_playing', frame_age=.1, capture_stale=False,
                           score_age=[.2, .3], fps=29.9, processing_ms=1.2, sequence=1000)
            healthy['publisher'].update(running=True, clients=2)
            visual = deepcopy(healthy)
            def status_fixture(route):
                route.fulfill(json=visual)
            page.route('**/api/status', status_fixture)
            page.locator('#camera-index').fill('1')
            page.locator('#cameras').evaluate("el => el.replaceChildren(new Option('1: USB Capture', '1'))")
            page.locator('[data-path="publish.websocket.port"]').fill('9005')
            page.evaluate("document.getElementById('profile').textContent='tournament.json'; document.getElementById('error').hidden=true")
            expect(page.locator('#p1')).to_have_text('198,430')
            expect(page.locator('#p2-presence')).to_have_text('Yes')
            for width, height, suffix in ((1120, 800, 'default'), (760, 560, 'minimum')):
                page.set_viewport_size({'width': width, 'height': height})
                for tab in ('session', 'obs', 'renderer', 'results'):
                    page.locator('#tab-'+tab).click()
                    expect(page.locator('#save-as')).to_be_visible()
                    expect(page.locator('#start')).to_be_disabled()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (suffix, tab)
                    if suffix == 'default' and tab == 'session':
                        assert page.locator('#advanced').bounding_box()['y'] < 750
                    page.screenshot(path=str(out / ('graphite-'+tab+'-'+suffix+'.png')), full_page=True)
                page.locator('#tab-session').click()
                visual.update(frame_age=4.2, capture_stale=True, score_age=[4.2, None], pending=True,
                              published={'state':'song_playing', 'players':[True,False],
                                         'score': {'p1_score':198430, 'p2_score':None}})
                expect(page.locator('#capture')).to_contain_text('Stale capture')
                expect(page.locator('#p2-presence')).to_have_text('No')
                expect(page.locator('#p2')).to_have_text('—')
                expect(page.locator('#p2-age')).to_have_text('No accepted read')
                expect(page.locator('#pending')).to_contain_text('Draft changes')
                page.screenshot(path=str(out / ('graphite-stale-'+suffix+'.png')), full_page=True)
                visual.update(phase='Error', error='Capture unavailable. Check the USB connection and start again.')
                expect(page.locator('#error')).to_contain_text('Capture unavailable')
                expect(page.locator('#start')).to_be_enabled()
                expect(page.locator('#stop')).to_be_disabled()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(out / ('graphite-error-'+suffix+'.png')), full_page=True)
                visual.clear()
                visual.update(deepcopy(healthy))
                expect(page.locator('#phase')).to_have_text('Running')
                page.evaluate("document.getElementById('error').hidden=true")
            page.set_viewport_size({'width': 1120, 'height': 800})
            page.locator('#tab-session').focus()
            page.locator('#tab-session').press('ArrowRight')
            expect(page.locator('#tab-obs')).to_be_focused()
            assert page.locator('#tab-obs').evaluate("el => getComputedStyle(el).outlineStyle") != 'none'
            page.locator('#tab-session').click()
            page.unroute('**/api/status', status_fixture)
            # A failed save must allow either keeping the editor or explicitly closing it.
            page.locator('#advanced > summary').click()
            page.locator('#config-json').fill('{ invalid json')
            page.evaluate('window.probeClosed=false')
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.evaluate('window.deskClose()')
            assert page.evaluate('window.probeClosed') is False
            page.once('dialog', lambda dialog: dialog.accept())
            page.evaluate('window.deskClose()')
            assert page.evaluate('window.probeClosed') is True
            assert not errors, errors
            write_json(out / 'report.json', dict(errors=errors, graphite_layout=True, minimum_width_no_overflow=True,
                        visual_status_fixtures=True, keyboard_focus_visible=True, integration_tabs=True, tab_keyboard_navigation=True,
                        tabs_preserved_draft=True, results_controls=True, results_apply_without_restart=True,
                        camera_action_failure_ui=True, snapshots_on_demand=True,
                        draft_survived_reopen=True, close_preserved_capture=True,
                        hidden_polling_stopped=True, secrets_masked=True, gui_save_cli_load=True, failed_save_close_recoverable=True))
            browser.close()
        print('Dashboard browser acceptance passed')
    finally:
        if meta:
            try:
                req = urllib.request.Request(meta['url']+'/api/action', data=b'{"action":"exit","confirmed":true}',
                        headers={'X-Desk-Token':meta['token'], 'Content-Type':'application/json'})
                urllib.request.urlopen(req, timeout=3).close()
                backend.wait(timeout=30)
            except Exception:
                backend.terminate()
                backend.wait(timeout=10)
        else:
            backend.terminate()
            backend.wait(timeout=10)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT/'.desktop-validation/ui')
    args=parser.parse_args()
    main(args.video, args.out.resolve())

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
            # Native restore/visibility callbacks can precede pywebviewready.
            page.evaluate('window.deskVisibility(true)')
            page.wait_for_timeout(400)
            assert not [r for r in requests if '/api/' in r], 'Request sent before session initialization'
            expect(page.locator('#error')).to_be_hidden()
            initial_failures = []
            def initial_config(route):
                if not initial_failures:
                    initial_failures.append(True)
                    route.abort('failed')
                else:
                    route.continue_()
            page.route('**/api/config', initial_config)
            bridge()
            expect(page.locator('#phase')).to_have_text('Stopped', timeout=10000)
            page.unroute('**/api/config', initial_config)
            expect(page.locator('#error')).to_be_hidden()
            # A temporary outage recovers without leaving a stale red banner.
            status_failures = []
            def unavailable_status(route):
                status_failures.append(True)
                route.abort('failed')
            page.route('**/api/status', unavailable_status)
            expect(page.locator('#connection')).to_contain_text('Reconnecting')
            expect(page.locator('#error')).to_be_hidden()
            page.unroute('**/api/status', unavailable_status)
            expect(page.locator('#connection')).to_have_text('Connected locally')
            assert status_failures
            # A bad token refreshes through the native bridge, without reloading the draft.
            page.evaluate("token = 'expired-test-token'")
            expect(page.locator('#connection')).to_have_text('Connected locally')
            page.wait_for_function('token !== "expired-test-token"')
            expect(page.locator('#error')).to_be_hidden()
            # A genuinely stale native session stays actionable and does not flood retries.
            stale_requests = []
            def stale_session(route):
                stale_requests.append(True)
                route.fulfill(status=403, json={'error': 'Invalid desk session'})
            page.route('**/api/status', stale_session)
            expect(page.locator('#connection')).to_contain_text('Close and reopen this panel')
            page.wait_for_timeout(1300)
            assert len(stale_requests) <= 3
            expect(page.locator('#error')).to_be_hidden()
            page.unroute('**/api/status', stale_session)
            expect(page.locator('#connection')).to_have_text('Connected locally', timeout=10000)
            # Repeated bridge-ready events must not reload and discard unsaved edits.
            page.evaluate("config.connection_probe = 'pending draft'")
            bridge()
            page.wait_for_timeout(300)
            assert page.evaluate('config.connection_probe') == 'pending draft'
            page.evaluate('delete config.connection_probe')
            # Network failure after a write must not retry a potentially completed action.
            failed_actions = []
            def failed_action(route):
                failed_actions.append(True)
                route.abort('failed')
            page.route('**/api/action', failed_action)
            message = page.evaluate("async () => {try {await api('action', 'POST', {action:'start'});} catch(e) {return e.message;}}")
            assert 'check its status' in message
            assert len(failed_actions) == 1
            page.unroute('**/api/action', failed_action)
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
            password = page.locator('[data-path="obs.password"]')
            password_eye = page.locator('#reveal-obs-password')
            expect(password_eye).to_be_visible()
            password_eye.click()
            expect(password).to_have_attribute('type', 'text')
            expect(password).to_have_value('')
            password_eye.press('Enter')
            expect(password).to_have_attribute('type', 'password')
            password.fill('desktop-ui-test-secret')
            page.locator('#obs-heading').click()
            expect(password_eye).to_be_visible()
            password_eye.click()
            expect(password).to_have_value('desktop-ui-test-secret')
            expect(password).to_have_attribute('type', 'text')
            password_eye.click()
            expect(password).to_have_attribute('type', 'password')
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
            replay_duplicates = page.locator('[data-path="results.allow_replay_duplicates"]')
            expect(replay_duplicates).not_to_be_checked()
            replay_duplicates.check()
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
            expect(names).to_be_enabled()
            screenshots_only = page.locator('[data-path="results.screenshots_only"]')
            expect(screenshots_only).not_to_be_checked()
            screenshots_only.check()
            expect(screenshots_only).to_be_enabled()
            expect(page.locator('#results-detail')).to_contain_text('Screenshots only')
            expect(page.locator('#phase')).to_have_text('Running')
            expect(page.locator('[data-path="results.output_directory"]')).to_have_value(export_folder)
            expect(names).not_to_be_checked()
            screenshots_only.uncheck()
            expect(screenshots_only).to_be_enabled()
            expect(page.locator('#results-detail')).not_to_contain_text('Screenshots only')
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
            expect(page.locator('#results-detail')).to_contain_text('Replay repeats enabled')
            expect(page.locator('#phase')).to_have_text('Running')
            assert 'desktop-ui-test' not in page.locator('#config-json').input_value()
            page.screenshot(path=str(out / 'results.png'), full_page=True)
            # Recovery remains hidden until requested. Use local fixtures; never send messages.
            expect(page.locator('#results-history')).not_to_have_attribute('open', '')
            assert not [r for r in requests if '/api/results/' in r]
            recovery = dict(delivery_available=True, discord=True, webhook_configured=True,
                records=[dict(event_id='recovery-test', revision=2, created_at=1, score_mode='ex',
                    players=[dict(present=True,name='P1',score=100),dict(present=True,name=None,score=200)],
                    parse_names=True, screenshot_confirmed=True, alternatives=[dict(id='alternative-1')],
                    delivery=dict(state='sent',message_url='https://discord.com/channels/1/2/3'),
                    name_update=dict(state='failed',error='Simulated update failure'))])
            page.route('**/api/results', lambda route: route.fulfill(json=recovery))
            page.route('**/api/results/recovery-test/*', lambda route: route.fulfill(
                content_type='image/png', body=(ROOT/'state_images/results_updated.png').read_bytes()))
            commands = []
            def recovery_action(route):
                args = route.request.post_data_json
                if args.get('action') == 'results_command':
                    commands.append(args)
                    route.fulfill(json=recovery)
                else: route.continue_()
            page.route('**/api/action', recovery_action)
            page.locator('#results-history > summary').click()
            expect(page.locator('#results-list')).to_contain_text('Simulated update failure')
            page.wait_for_function('document.querySelector("#results-list img")?.naturalWidth > 0')
            assert not [r for r in requests if '/alternative-1' in r]
            page.get_by_role('button', name='Retry name update', exact=True).click()
            page.wait_for_timeout(300)
            assert commands[-1]['command'] == 'retry_names'
            page.locator('#results-list details > summary').click()
            page.wait_for_function('document.querySelectorAll("#results-list img").length === 2')
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.get_by_role('button', name='Republish', exact=True).click()
            assert len(commands) == 1
            page.screenshot(path=str(out/'results-recovery.png'), full_page=True)
            recovery['records'][0].update(screenshots_only=True, parse_names=False,
                screenshot_confirmed=False, revision=3,
                players=[dict(present=True, name=None, score=None)] * 2,
                name_update=dict(state='idle'))
            expect(page.locator('#results-list')).to_contain_text('Screenshots only')
            expect(page.locator('#results-list')).not_to_contain_text('unconfirmed')
            expect(page.locator('#results-list')).not_to_contain_text('Names incomplete')
            page.locator('#results-history > summary').click()
            before_images = len([r for r in requests if '/api/results/' in r])
            page.wait_for_timeout(1100)
            assert len([r for r in requests if '/api/results/' in r]) == before_images
            page.unroute('**/api/results')
            page.unroute('**/api/results/recovery-test/*')
            page.unroute('**/api/action', recovery_action)
            page.reload()
            bridge()
            page.locator('#tab-results').click()
            expect(names).not_to_be_checked()
            expect(webhook).to_have_value('[unchanged secret]')
            webhook_eye = page.locator('#reveal-discord-webhook')
            expect(webhook_eye).to_be_visible()
            webhook_eye.click()
            expect(webhook).to_have_attribute('type', 'text')
            expect(webhook).to_have_value('https://discord.com/api/webhooks/1/desktop-ui-test')
            expect(webhook_eye).to_have_attribute('aria-label', 'Hide Discord webhook')
            assert '/desktop-ui-test' not in page.locator('#config-json').input_value()
            # Editing a revealed credential must persist the new value, not the placeholder.
            webhook.fill('https://discord.com/api/webhooks/1/desktop-ui-replacement')
            webhook_eye.click()
            expect(webhook).to_have_attribute('type', 'password')
            webhook_eye.click()
            expect(webhook).to_have_value('https://discord.com/api/webhooks/1/desktop-ui-replacement')
            webhook.fill('https://discord.com/api/webhooks/1/desktop-ui-test')
            webhook_eye.click()
            expect(webhook_eye).to_be_visible()
            expect(filename_names).not_to_be_checked()
            expect(page.locator('[data-path="results.output_directory"]')).to_have_value(export_folder)
            page.locator('#tab-results').press('ArrowLeft')
            expect(page.locator('#tab-renderer')).to_be_focused()
            page.locator('#tab-renderer').press('Home')
            expect(page.locator('#panel-session')).to_be_visible()
            expect(page.locator('#tab-session')).to_be_focused()
            page.locator('#tab-session').press('ArrowRight')
            expect(page.locator('#panel-obs')).to_be_visible()
            expect(password).to_have_value('[unchanged secret]')
            expect(password_eye).to_be_visible()
            password_eye.click()
            expect(password).to_have_attribute('type', 'text')
            expect(password).to_have_value('desktop-ui-test-secret')
            expect(password_eye).to_have_attribute('aria-pressed', 'true')
            assert 'desktop-ui-test-secret' not in page.locator('#config-json').input_value()
            password_eye.click()
            expect(password).to_have_attribute('type', 'password')
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
            assert load_config(saved)['results']['allow_replay_duplicates'] is True
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
            measured_rates = {key: status[key] for key in ('fps', 'processing_fps', 'processing_avg_ms', 'source_fps')}
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
                           score_age=[.2, .3], fps=26, processing_ms=1.2, sequence=1000,
                           processing_fps=100, processing_avg_ms=10, source_fps=30)
            healthy['publisher'].update(running=True, clients=2)
            visual = deepcopy(healthy)
            def status_fixture(route):
                route.fulfill(json=visual)
            page.route('**/api/status', status_fixture)
            # A repeated recording must explain why it creates no new outputs.
            saved_results = deepcopy(visual.get('results'))
            visual['results'] = dict(enabled=True, discord=True, phase='already_saved',
                                     error=None, deduplicated=1, needs_attention=0)
            expect(page.locator('#results-summary')).to_contain_text('Replay already saved')
            page.locator('#tab-results').click()
            expect(page.locator('#results-detail')).to_contain_text('no new screenshot or automatic Discord post')
            expect(page.locator('#results-detail')).to_contain_text('Recent results & recovery')
            visual['results']['error'] = 'Screenshot folder is unavailable'
            expect(page.locator('#results-detail')).to_have_text('Screenshot folder is unavailable')
            visual['results'] = saved_results
            page.locator('#tab-session').click()
            expect(page.locator('#results-summary')).not_to_contain_text('Replay already saved')
            page.locator('#camera-index').fill('1')
            page.locator('#cameras').evaluate("el => el.replaceChildren(new Option('1: USB Capture', '1'))")
            page.locator('[data-path="publish.websocket.port"]').fill('9005')
            page.evaluate("document.getElementById('profile').textContent='tournament.json'; document.getElementById('error').hidden=true")
            expect(page.locator('#p1')).to_have_text('198,430')
            expect(page.locator('#p2-presence')).to_have_text('Yes')
            expect(page.locator('#throughput')).to_contain_text('Processing capacity: 100.0 fps (10.0 ms/frame)')
            expect(page.locator('#throughput')).to_contain_text('Throughput: 26.0 fps · File: 30.0 fps')
            # New panel / pre-update persistent backend: the old timing field
            # remains useful and must not be mistaken for the rolling average.
            del visual['processing_fps']
            del visual['processing_avg_ms']
            visual['processing_ms'] = 10
            expect(page.locator('#throughput')).to_contain_text('Processing capacity: 100.0 fps (10.0 ms, last frame)')
            visual['processing_ms'] = 0
            expect(page.locator('#throughput')).to_contain_text('waiting for timing sample')
            visual['processing_ms'] = 10
            visual.update(frame_age=3, capture_stale=True)
            expect(page.locator('#throughput')).to_contain_text('no recent frames · Throughput: 0.0 fps')
            visual.update(phase='Ended')
            expect(page.locator('#throughput')).to_contain_text('playback ended')
            visual.clear()
            visual.update(deepcopy(healthy))
            expect(page.locator('#throughput')).to_contain_text('Processing capacity: 100.0 fps (10.0 ms/frame)')
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
                        distinct_processing_and_source_rates=True, legacy_timing_and_unavailable_states=True,
                        measured_rates=measured_rates,
                        visual_status_fixtures=True, keyboard_focus_visible=True, integration_tabs=True, tab_keyboard_navigation=True,
                        tabs_preserved_draft=True, results_controls=True, results_apply_without_restart=True,
                        collapsed_results_recovery=True, authenticated_thumbnails_on_demand=True,
                        name_update_retry=True, republish_confirmation=True,
                        camera_action_failure_ui=True, snapshots_on_demand=True,
                        draft_survived_reopen=True, close_preserved_capture=True,
                        hidden_polling_stopped=True, session_startup_gated=True, connection_recovery=True,
                        expired_session_recovery=True, writes_not_retried=True, secrets_masked=True, gui_save_cli_load=True, failed_save_close_recoverable=True))
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

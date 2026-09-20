"""Real browser + production publisher tests (optional Playwright test dependency).

Install Playwright and its Chromium browser, then run unittest discovery for this
file. DDRCV_TEST_BROWSER_CHANNEL=msedge can use an installed Microsoft Edge.
"""
from importlib.util import find_spec
import json
import os
from pathlib import Path
import socket
import tempfile
import runpy
import unittest

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'browser_overlay'
prepare_overlay = runpy.run_path(str(EXAMPLE / 'prepare.py'))['prepare_overlay']


@unittest.skipUnless(find_spec('playwright'), 'Install Playwright to run browser overlay tests')
class BrowserOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(
                headless=True, channel=os.environ.get('DDRCV_TEST_BROWSER_CHANNEL') or None)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        from ddrcv.publish.websocket_publisher import WebSocketPublisher
        self.temp = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.publisher = WebSocketPublisher(host='127.0.0.1', port=port, delay=.02)
        self.publisher.start()
        self.path = prepare_overlay(self.temp.name, f'ws://127.0.0.1:{port}')
        self.context = self.browser.new_context(viewport={'width': 960, 'height': 240})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()
        self.publisher.stop()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    def expect_text(self, selector, text):
        from playwright.sync_api import expect
        expect(self.page.locator(selector)).to_have_text(text)

    def send(self, **changes):
        snapshot = dict(state='song_playing', players=[True, True],
                        score={'p1_score': 0, 'p2_score': 1000000},
                        player_names={'p1': 'ALICE', 'p2': 'BOB'})
        snapshot.update(changes)
        self.publisher.send_message(snapshot)

    def test_retained_snapshot_zero_money_and_transparent_layout(self):
        self.send()
        self.page.goto(self.path.as_uri())
        self.expect_text('#p1-name', 'ALICE')
        self.expect_text('#p1-score', '0')
        self.expect_text('#p2-score', '1,000,000')
        self.expect_text('#connection', 'Connected · Gameplay')
        self.assertEqual(self.page.evaluate('getComputedStyle(document.body).backgroundColor'), 'rgba(0, 0, 0, 0)')
        self.assertTrue(self.page.evaluate('document.querySelector("main").getBoundingClientRect().bottom <= innerHeight'))
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.send(player_names={'p1': 'A' * 200, 'p2': '<img src=x onerror=alert(1)>'})
        self.expect_text('#p2-name', '<img src=x onerror=alert(1)>')
        self.assertEqual(self.page.locator('img').count(), 0)
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))

    def test_null_missing_invalid_and_absent_values_replace_prior_state(self):
        self.send()
        self.page.goto(self.path.as_uri())
        self.expect_text('#p1-name', 'ALICE')
        for bad in (None, -1, '123', True, 1.5, {}, [], 9007199254740992):
            self.send(score={'p1_score': bad}, player_names=None)
            self.expect_text('#p1-score', '—')
            self.expect_text('#p2-score', '—')
            self.expect_text('#p1-name', 'P1')
            self.send()
            self.expect_text('#p1-score', '0')
        self.send(players=[False, True], player_names={'p1': 'OLD', 'p2': 'ONLY P2'})
        self.expect_text('#p1-name', 'P1')
        self.expect_text('#p1-score', '—')
        self.expect_text('#p2-name', 'ONLY P2')
        self.expect_text('#p2-score', '1,000,000')
        self.publisher.send_message({'state': 'song_playing'})
        self.expect_text('#p2-name', 'P2')
        self.expect_text('#p2-score', '—')

    def test_states_resets_and_results_do_not_override_gameplay(self):
        self.page.goto(self.path.as_uri())
        for state in ('song_playing', 'song_result', 'song_select', 'login', 'song_splash', 'total_result', 'unknown', 'future_state', 'toString'):
            self.send(state=state, player_names={'p1': state}, results={'latest': {'players': [{'score': 999}]}})
            self.expect_text('#p1-name', state)
            self.expect_text('#p1-score', '0' if state in ('song_playing', 'song_result') else '—')
        self.expect_text('#connection', 'Connected · Unknown screen')
        self.send(score={'p1_score': 700, 'p2_score': 900})
        self.expect_text('#p1-score', '700')
        self.send(score=None, player_names={})
        self.expect_text('#p1-score', '—')
        self.expect_text('#p1-name', 'P1')
        self.send(score={'p1_score': 2})
        self.expect_text('#p1-score', '2')

    def test_disconnect_clears_and_reconnect_replaces_names(self):
        self.send()
        self.page.goto(self.path.as_uri())
        self.expect_text('#p1-name', 'ALICE')
        self.publisher.stop()
        self.expect_text('#p1-score', '—')
        self.expect_text('#p1-name', 'P1')
        self.send(score={'p2_score': 7}, player_names=None, players=[False, True])
        self.publisher.start()
        self.expect_text('#connection', 'Connected · Gameplay')
        self.expect_text('#p1-score', '—')
        self.expect_text('#p2-name', 'P2')
        self.expect_text('#p2-score', '7')

    def test_malformed_messages_recover_and_silence_is_not_disconnect(self):
        routes = []
        self.page.route_web_socket('**/*', lambda route: routes.append(route))
        self.page.clock.install()
        self.page.goto(self.path.as_uri())
        self.expect_text('#connection', 'Connected · waiting for state')
        route = routes[0]
        for invalid in ('{broken', 'null', '[]', '123', '{}'):
            route.send(json.dumps({'state': 'song_playing', 'players': [True, True], 'score': {'p1_score': 10}}))
            self.expect_text('#p1-score', '10')
            route.send(invalid)
            self.expect_text('#connection', 'Connected · invalid state')
            self.expect_text('#p1-score', '—')
        route.send(json.dumps({'state': 'song_playing', 'players': [True], 'score': {'p1_score': 0}}))
        self.expect_text('#p1-score', '0')
        self.page.clock.fast_forward(65000)
        self.expect_text('#connection', 'Connected · Gameplay')
        self.expect_text('#p1-score', '0')
        self.expect_text('#received', 'Received 65s ago')

    def test_invalid_url_is_visible_and_override_uses_configured_endpoint(self):
        self.page.goto(self.path.as_uri() + '?ws=https://example.org')
        self.expect_text('#connection', 'Invalid feed URL · use ws://host:port')
        self.expect_text('#p1-score', '—')
        self.send()
        self.page.goto(self.path.as_uri() + f'?ws=ws://127.0.0.1:{self.publisher.port}')
        self.expect_text('#p2-score', '1,000,000')

    def test_retry_backoff_is_capped_and_resets_after_valid_state(self):
        routes = []
        self.page.route_web_socket('**/*', lambda route: routes.append(route))
        self.page.clock.install()
        self.page.goto(self.path.as_uri())
        self.expect_text('#connection', 'Connected · waiting for state')
        for delay in (500, 1000, 2000, 4000, 8000, 10000, 10000):
            count = len(routes)
            routes[-1].close()
            self.expect_text('#connection', 'Disconnected · reconnecting…')
            self.page.clock.run_for(delay - 1)
            self.assertEqual(len(routes), count)
            self.page.clock.run_for(1)
            self.expect_text('#connection', 'Connected · waiting for state')
            self.assertEqual(len(routes), count + 1)
        routes[-1].send('{"state":"song_playing"}')
        self.expect_text('#connection', 'Connected · Gameplay')
        routes[-1].close()
        self.expect_text('#connection', 'Disconnected · reconnecting…')
        self.page.clock.run_for(500)
        self.expect_text('#connection', 'Connected · waiting for state')



if __name__ == '__main__':
    unittest.main()

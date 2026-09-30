"""Guided catalog workflows in both real browser interfaces, using isolated catalogs.

Optional Playwright dependency; DDRCV_TEST_BROWSER_CHANNEL=msedge uses local Edge.
DDRCV_CATALOG_SCREENSHOTS may name an output directory for visual inspection.
"""
from copy import deepcopy
from importlib.util import find_spec
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_catalog_archive as archive_tests
import test_desktop as desktop_tests
from test_workbench import make_engine
from ddrcv.desktop.app import create_app as desktop_app
from ddrcv.desktop.controller import Desk
from ddrcv.workbench.app import create_app as workbench_app
from ddrcv.workbench.controller import Workbench
from ddrcv.jacket_lookup import assets
from ddrcv.jacket_lookup.config import catalog_path, validate_config
from ddrcv.jacket_lookup.operations import CatalogPreparation


@unittest.skipUnless(find_spec('playwright'), 'Install Playwright for catalog UI tests')
class CatalogWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True,
                channel=os.environ.get('DDRCV_TEST_BROWSER_CHANNEL') or None)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.fixture = archive_tests.ArchiveTests('test_direct_offline_load_exact_matching_and_chart_provenance')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_desktop_guided_catalog(self):
        self.workflow('desktop')

    def test_workbench_guided_catalog(self):
        self.workflow('workbench')

    def workflow(self, name):
        from playwright.sync_api import expect
        from werkzeug.serving import make_server
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        fixture = self.fixture
        original = fixture.path.read_bytes()
        directory = Path(self.temp.name)
        cfg = validate_config(dict(assets_dir=str(directory/'empty-cache')))
        video = directory/'operator-test-video.mp4'
        video.write_bytes(b'Capture is substituted by the test runtime.')
        if name == 'desktop':
            owner = Desk(directory/'desktop', desktop_tests.FakeRuntime)
            baseline = owner.status()
            class Runtime(desktop_tests.FakeRuntime):
                def __init__(self, config):
                    super().__init__(config)
                    lookup = assets.load(config['song_lookup']) if config['song_lookup']['enabled'] else None
                    self.bundle = lookup.bundle_info if lookup else None
                    self.catalog_stamp = lookup._catalog_stamp if lookup else None
                def status(self):
                    value = deepcopy(baseline)
                    value.update(phase=self.phase, song_lookup_status=dict(
                        phase='ready' if self.bundle else 'disabled', catalog=self.bundle, catalog_stamp=self.catalog_stamp, error=None))
                    return value
            owner.runtime_factory = Runtime
            draft = owner.config()['draft']
            draft['song_lookup'] = cfg
            draft['ingest'] = dict(video=dict(path=str(video), resize_to_720p=False))
            owner.edit(draft)
            app = desktop_app(owner, 'guided-catalog')
        else:
            owner = Workbench(directory/'workbench', engine=make_engine(), start_publisher=False)
            owner.settings['song_lookup'] = cfg
            app = workbench_app(owner)
        self.addCleanup(owner.close)
        server = make_server('127.0.0.1', 0, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        context = self.browser.new_context(viewport={'width': 1120, 'height': 800})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        picker = {'path': None}
        if name == 'desktop':
            page.expose_function('pickCatalog', lambda kind: picker['path'])
        else:
            owner.browse_path = lambda *args: picker['path']

        def visit():
            page.goto(f'http://127.0.0.1:{server.server_port}')
            if name == 'desktop':
                page.evaluate("""() => {window.pywebview={api:{session:async()=>({token:'guided-catalog'}),pick:window.pickCatalog}}; window.dispatchEvent(new Event('pywebviewready'));}""")
                page.wait_for_function('loaded')
            else:
                page.wait_for_function('initialized')
            page.locator('#tab-song').click()

        def activation():
            if name == 'desktop':
                running = owner.runtime is not None and owner.runtime.phase == 'Running'
                return page.locator('#apply' if running else '#start')
            return page.locator('#song-apply')

        def load():
            picker['path'] = str(fixture.path)
            page.locator('#song-load').click()
            expect(page.locator('#song-catalog-state')).to_contain_text('Catalog validated')
            expect(page.locator('#song-load')).to_be_enabled()

        visit()
        expect(page.locator('#song-event-help')).to_contain_text('Dia Del Ritmo 2026')
        expect(page.locator('#song-catalog-state')).to_contain_text('No prepared catalog')
        expect(page.locator('#song-readiness')).to_contain_text('Recognition disabled')
        if name == 'desktop':
            expect(page.locator('#panel-song #song-apply')).to_have_count(0)
            expect(activation()).to_be_visible()
        else:
            expect(activation()).to_be_disabled()
        page.locator('#song-load').click()
        expect(page.locator('#song-load')).to_be_enabled()
        self.assertEqual(page.locator('#song-assets').input_value(), '')
        load()
        self.assertIsNone(owner.runtime if name == 'desktop' else owner.source)
        visit()
        expect(page.locator('#song-catalog-state')).to_contain_text('Catalog validated' if name == 'desktop' else 'No prepared catalog')
        # Workbench draft controls are intentionally not applied/saved by Load.
        if name == 'workbench':
            load()
        owner.catalog_preparation.close()
        owner.catalog_preparation = CatalogPreparation()
        page.locator('#tab-song').click()
        expect(page.locator('#song-catalog-state')).to_contain_text('Catalog found — checked when activated')
        load()
        page.locator('#song-mode').select_option('full')
        expect(page.locator('#song-mismatch')).to_be_visible()
        expect(page.locator('#song-build')).to_be_disabled()
        page.locator('#song-use-loaded').click()
        expect(page.locator('#song-mode')).to_have_value('event')
        expect(page.locator('#song-catalog-state')).to_contain_text('Catalog validated')
        page.locator('#song-mode').select_option('full')
        expect(page.locator('#song-mismatch')).to_be_visible()
        built = []
        gate = threading.Event()
        full = deepcopy(fixture.selection)
        full['catalog'].update(mode='full', event=None, metadata_dataset='ddr_world')
        def prepare(config, *, refresh, progress):
            if not gate.wait(10):
                raise RuntimeError('Test build was not released')
            self.assertTrue(refresh)
            self.assertIsNone(config['catalog_file'])
            target = catalog_path(config)
            self.assertNotEqual(target, fixture.path)
            assets._publish(target, fixture.metadata, fixture.arrays, full, config)
            built.append(target)
            return assets.check(config)
        with patch.object(assets, 'prepare', side_effect=prepare):
            page.locator('#song-build-default').click()
            expect(page.locator('#song-build')).to_be_disabled()
            expect(page.locator('#song-load')).to_be_disabled()
            gate.set()
            expect(page.locator('#song-catalog-state')).to_contain_text('Full DDR / WORLD · Catalog validated')
        self.assertEqual(len(built), 1)
        self.assertEqual(fixture.path.read_bytes(), original)
        with patch.object(assets, 'prepare', side_effect=OSError('Offline test')):
            page.locator('#song-build').click()
            expect(page.locator('#song-operation')).to_contain_text('Offline test')
        expect(page.locator('#song-catalog-state')).to_contain_text('Catalog validated')
        self.assertEqual(fixture.path.read_bytes(), original)
        bad = directory/'bad.ddrcatalog'
        bad.write_bytes(b'not a catalog')
        picker['path'] = str(bad)
        page.locator('#song-load').click()
        expect(page.locator('#error')).to_be_visible()
        self.assertEqual(page.locator('#song-assets').input_value(), '')
        load()
        # A late response for an older selection must never replace the new selection.
        held = []
        stale = assets.describe(fixture.cfg)
        def route_info(route):
            request = route.request.post_data_json
            if request.get('action') == 'song_info' and request['config'].get('event') == 'delayed-event':
                held.append(route)
            else:
                route.continue_()
        page.route('**/api/action', route_info)
        with page.expect_request(lambda request: request.url.endswith('/api/action') and
                request.post_data_json.get('action') == 'song_info' and
                request.post_data_json['config'].get('event') == 'delayed-event'):
            page.locator('#song-event').fill('delayed-event')
        page.locator('#song-event').fill('new-event')
        expect(page.locator('#song-mismatch-message')).to_contain_text('new-event')
        self.assertTrue(held)
        held.pop().fulfill(status=200, content_type='application/json', body=json.dumps(stale))
        page.unroute('**/api/action', route_info)
        expect(page.locator('#song-mismatch-message')).to_contain_text('new-event')
        page.locator('#song-use-loaded').click()
        expect(page.locator('#song-catalog-state')).to_contain_text('Catalog validated')
        page.locator('#song-enabled').check()
        expect(activation()).to_be_enabled()
        if name == 'desktop':
            with patch.object(owner, '_prepare', side_effect=ValueError('Choose a valid source first')):
                activation().click()
                expect(page.locator('#error')).to_contain_text('Choose a valid source first')
                self.assertIsNone(owner.runtime)
        activation().click()
        if name == 'desktop':
            expect(page.locator('#song-readiness')).to_contain_text('Recognition active')
            self.assertTrue(owner.runtime.thread)
            self.assertEqual(owner.runtime.config['ingest']['video']['path'], str(video))
            old = owner.runtime
            page.locator('#song-style').select_option('double')
            expect(page.locator('#song-readiness')).to_contain_text('Changes pending')
            expect(activation()).to_have_text('Apply and Restart')
            activation().click()
            expect(page.locator('#song-readiness')).to_contain_text('Recognition active')
            self.assertEqual(old.stop_calls, 1)
            self.assertEqual(owner.runtime.config['song_lookup']['style'], 'double')
        else:
            expect(page.locator('#song-active-version')).to_contain_text('Applied catalog: event')
            expect(page.locator('#song-activation-help')).to_contain_text('open a camera or video')
            self.assertTrue(owner.settings['song_lookup']['enabled'])
            self.assertIsNone(owner.source)
        visit()
        expect(page.locator('#song-catalog-state')).to_contain_text('Catalog validated')
        # Replacing a file with the same metadata still needs fresh validation.
        fixture.write()
        page.locator('#tab-song').click()
        expect(page.locator('#song-catalog-state')).to_contain_text('Catalog found — checked when activated')
        expect(page.locator('#song-readiness')).to_contain_text('Changes pending')
        activation().click()
        expect(page.locator('#song-catalog-state')).to_contain_text('Catalog validated')
        # Replace on-disk metadata while the active session retains its old version.
        selection = deepcopy(fixture.selection)
        row = selection['catalog']['records'][0]
        row['name'] = 'Song 0 <img src=x onerror=alert(1)>'
        selection['unsupported'] = [dict(record_id=row['record_id'], style='single', difficulty='expert', reason='unsupported_artwork')]
        selection['catalog']['commit'] = 'c'*40
        fixture.write(selection=selection)
        page.locator('#tab-song').click()
        expect(page.locator('#song-catalog-state')).to_contain_text('Catalog found — checked when activated')
        expect(page.locator('#song-active-version')).to_contain_text('selected file differs')
        page.locator('#song-coverage > summary').click()
        expect(page.locator('#song-coverage-list')).to_contain_text('Song 0 <img')
        self.assertEqual(page.locator('#song-coverage-list img').count(), 0)
        for width, height in ((1120, 800), (720, 700)):
            page.set_viewport_size({'width': width, 'height': height})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.locator('#song-version-details > summary').focus()
            page.keyboard.press('Enter')
            self.assertTrue(page.locator('#song-version-details').evaluate('(node) => node.open'))
            output = os.environ.get('DDRCV_CATALOG_SCREENSHOTS')
            if output:
                target = Path(output); target.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(target/f'{name}-{width}.png'), full_page=True)
            page.keyboard.press('Enter')
        activation().click()
        expect(page.locator('#song-catalog-state')).to_contain_text('Ready with coverage warnings')
        page.locator('#song-coverage > summary').click()
        page.set_viewport_size({'width': 1120, 'height': 800})
        output = os.environ.get('DDRCV_CATALOG_SCREENSHOTS')
        if output:
            page.screenshot(path=str(Path(output)/f'{name}-overview.png'), full_page=True)
        # Exercise plain-language chart output through the actual status renderer.
        def chart_status(route):
            response = route.fetch()
            data = response.json()
            data['published']['song'] = dict(title='Coverage example', charts=dict(
                p1=dict(difficulty='expert', max_ex=None, status='chart_outside_pool'),
                p2=dict(difficulty='basic', max_ex=0, status='confirmed')))
            route.fulfill(response=response, json=data)
        page.route('**/api/status', chart_status)
        expect(page.locator('#song-charts')).to_contain_text('Outside selected pool')
        expect(page.locator('#song-charts')).to_contain_text('Max EX 0')
        self.assertNotIn('Max EX Max EX', page.locator('#song-charts').text_content())
        page.unroute('**/api/status', chart_status)
        # Losing the catalog must not prevent disabling this optional feature.
        fixture.path.unlink()
        page.locator('#tab-song').click()
        expect(page.locator('#song-catalog-state')).to_contain_text('No prepared catalog')
        if name == 'desktop':
            expect(page.locator('#panel-song #song-apply')).to_have_count(0)
            expect(activation()).to_be_visible()
        else:
            expect(activation()).to_be_disabled()
        page.locator('#song-enabled').uncheck()
        expect(activation()).to_be_enabled()
        activation().click()
        expect(page.locator('#song-readiness')).to_contain_text('Recognition disabled')
        self.assertFalse(owner.runtime.config['song_lookup']['enabled'] if name == 'desktop' else owner.settings['song_lookup']['enabled'])
        self.assertEqual(errors, [])

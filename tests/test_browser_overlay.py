"""Standalone overlay example assets and configuration utility."""
from html.parser import HTMLParser
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'browser_overlay'
prepare_overlay = runpy.run_path(str(EXAMPLE / 'prepare.py'))['prepare_overlay']


class BodyParser(HTMLParser):
    parsed_feed = None

    def handle_starttag(self, tag, attrs):
        if tag == 'body':
            self.parsed_feed = dict(attrs)['data-feed']


class OverlayTests(unittest.TestCase):
    def test_export_is_self_contained_and_escapes_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = 'ws://localhost:9012/?x="<&'
            path = prepare_overlay(tmp, feed)
            parser = BodyParser()
            parser.feed(path.read_text(encoding='utf-8'))
            self.assertEqual(parser.parsed_feed, feed)
            self.assertEqual({p.name for p in Path(tmp).iterdir()}, {'index.html', 'overlay.js', 'overlay.css'})
            for name in ('overlay.js', 'overlay.css'):
                self.assertEqual((Path(tmp) / name).read_text(encoding='utf-8'),
                                 EXAMPLE.joinpath(name).read_text(encoding='utf-8'))

    def test_reprepare_keeps_path_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = prepare_overlay(tmp)
            custom = Path(tmp) / 'operator-notes.txt'
            custom.write_text('keep')
            self.assertEqual(prepare_overlay(tmp, 'ws://localhost:9013'), first)
            self.assertIn('data-feed="ws://localhost:9013"', first.read_text())
            self.assertEqual(custom.read_text(), 'keep')

    def test_cli_runs_outside_checkout_without_package_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'OBS overlay'
            result = subprocess.run([sys.executable, '-I', '-B', str(EXAMPLE / 'prepare.py'),
                                     str(output), '--feed', 'ws://localhost:9017'],
                                    cwd=tmp, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), str(output / 'index.html'))
            self.assertIn('data-feed="ws://localhost:9017"',
                          (output / 'index.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()

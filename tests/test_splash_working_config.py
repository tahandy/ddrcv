"""Working defaults reach each branch; explicit comparison overrides still work."""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from experiments.jacket_lookup.configuration import WORKING_CONFIG
from experiments.jacket_lookup.names import PerPlayerNameReader
from experiments.jacket_lookup.splash_demo import build_parser
from experiments.jacket_lookup.threaded import ThreadedSplashLookup


class WorkingConfigTests(unittest.TestCase):
    def test_no_flag_demo_uses_measured_configuration(self):
        args = build_parser().parse_args(['--image', 'frame.png'])
        self.assertEqual((args.catalog, args.style, args.difficulty_method,
                          args.name_method, args.name_threads, args.worker_qos),
                         ('event', 'single', 'template', 'per-player', 1, 'high'))
        with self.assertRaises(FrozenInstanceError): WORKING_CONFIG.high_qos = False

    def test_explicit_comparison_options_override_defaults(self):
        args = build_parser().parse_args(['--image', 'frame.png', '--worker-qos', 'system',
            '--name-method', 'batch', '--name-threads', '2', '--difficulty-method', 'ocr'])
        self.assertEqual((args.worker_qos, args.name_method, args.name_threads,
                          args.difficulty_method), ('system', 'batch', 2, 'ocr'))

    def test_name_policy_reaches_both_workers_and_can_be_disabled(self):
        for override in ({}, {'high_qos': False}):
            calls = []
            @contextmanager
            def policy(enabled):
                calls.append((enabled, threading.current_thread().name))
                yield
            readers = [Mock(), Mock()]
            for reader in readers:
                reader.read.side_effect = lambda crops: {k:'NAME' for k in crops}
            with patch('experiments.jacket_lookup.execution.worker_qos', policy):
                with PerPlayerNameReader(reader_factory=Mock(side_effect=readers), **override) as names:
                    self.assertEqual(names.config['ocr']['num_threads'], 1)
                    crop = np.zeros((34,212,3), np.uint8)
                    self.assertEqual(names.read({0:crop, 1:crop}), {0:'NAME', 1:'NAME'})
            self.assertEqual(sorted(calls), [(not override, 'splash-name-p1'),
                                             (not override, 'splash-name-p2')])

    def test_chart_policy_reaches_jacket_and_difficulty_and_can_be_disabled(self):
        for override in ({}, {'high_qos': False}):
            calls = []
            @contextmanager
            def policy(enabled):
                calls.append((enabled, threading.current_thread().name))
                yield
            lookup = Mock()
            lookup._get_splash_detector.return_value.match.return_value = (
                True, dict(p1_present=True, p2_present=False))
            lookup.lookup.return_value = dict(accepted=False, timings_ms={})
            reader = Mock()
            reader.recognize.return_value = dict(accepted=False)
            with patch('experiments.jacket_lookup.execution.worker_qos', policy), \
                 patch('experiments.jacket_lookup.threaded.worker_qos', policy):
                with ThreadedSplashLookup(lookup, difficulty_reader=reader, **override) as charts:
                    result = charts.analyze(np.zeros((720,1280,3), np.uint8))
            self.assertEqual(result['difficulty_method'], 'template')
            self.assertCountEqual(calls, [(not override, threading.current_thread().name),
                                          (not override, 'splash-difficulty')])


if __name__ == '__main__': unittest.main()

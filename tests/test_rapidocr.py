"""No model/network required unless DDRCV_TEST_OCR_MODEL is explicitly set."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from ddrcv.ocr import OCRResult, RapidOCRRecognizer, get_rapidocr, prepare_ddr_crop
from ddrcv.ocr import rapid


class RapidOCRTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((12, 32, 3), 100, dtype=np.uint8)

    def test_import_and_construction_are_lightweight(self):
        source = (
            'import sys; from ddrcv.ocr import RapidOCRRecognizer; '
            'r = RapidOCRRecognizer(); '
            'assert not any(x in sys.modules for x in '
            '("rapidocr", "onnxruntime", "easyocr", "torch", "cv2", "numpy"))'
        )
        subprocess.run([sys.executable, '-B', '-c', source], check=True)

    def test_default_is_shared_across_threads(self):
        start = Barrier(8)
        def get(_):
            start.wait(timeout=5)
            return get_rapidocr()
        with patch.object(rapid, '_default_recognizer', None):
            with ThreadPoolExecutor(max_workers=8) as pool:
                instances = list(pool.map(get, range(8)))
            self.assertTrue(all(instance is instances[0] for instance in instances))
            self.assertIsNone(instances[0]._engine)

    def test_concurrent_calls_load_once_and_never_overlap(self):
        active = 0
        maximum = 0
        counter_lock = Lock()
        start = Barrier(8)
        def backend(request):
            nonlocal active, maximum
            with counter_lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(.005)  # release the GIL so an absent inference lock fails
            values = [str(int(image[0, 0, 0])) for image in request.img]
            with counter_lock:
                active -= 1
            return SimpleNamespace(txts=values, scores=[.9] * len(values))
        recognizer = RapidOCRRecognizer()
        def recognize(value):
            start.wait(timeout=5)
            recognizer.warmup()
            return recognizer.recognize(np.full_like(self.image, value)).text
        with patch.object(rapid, '_build_engine', return_value=(backend, SimpleNamespace)) as build:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(recognize, range(8)))
            build.assert_called_once()
        self.assertEqual(results, list(map(str, range(8))))
        self.assertEqual(maximum, 1)

    def test_order_whitespace_and_immutable_results(self):
        def backend(request):
            return SimpleNamespace(txts=[' ZERO. ', '  ', '999,760'], scores=[.9, .8, .99])
        with patch.object(rapid, '_build_engine', return_value=(backend, SimpleNamespace)):
            results = RapidOCRRecognizer().recognize_many(self.image for _ in range(3))
        self.assertEqual(results, [OCRResult('ZERO.', .9), OCRResult('', 0), OCRResult('999,760', .99)])
        with self.assertRaises(FrozenInstanceError):
            results[0].text = 'changed'

    def test_rgb_gray_and_noncontiguous_inputs_are_copied(self):
        seen = []
        def backend(request):
            for image in request.img:
                self.assertTrue(image.flags.c_contiguous)
                seen.append(image.copy())
                image[:] = 0  # even a mutating backend must not touch callers
            return SimpleNamespace(txts=['X'] * len(request.img), scores=[.9] * len(request.img))
        source = np.arange(12 * 32 * 3, dtype=np.uint8).reshape(12, 32, 3)
        original = source.copy()
        gray = source[:, :, 0].copy()
        with patch.object(rapid, '_build_engine', return_value=(backend, SimpleNamespace)):
            recognizer = RapidOCRRecognizer()
            recognizer.recognize(source[:, ::2], color_order='rgb')
            recognizer.recognize(gray)
        np.testing.assert_array_equal(seen[0], original[:, ::2, ::-1])
        np.testing.assert_array_equal(seen[1], np.repeat(gray[:, :, None], 3, axis=2))
        np.testing.assert_array_equal(source, original)
        np.testing.assert_array_equal(gray, original[:, :, 0])

    def test_empty_batch_and_invalid_inputs_never_load(self):
        recognizer = RapidOCRRecognizer()
        invalid = [None, 'file.png', b'png', np.zeros((3, 4), dtype=float),
                   np.zeros((0, 4, 3), dtype=np.uint8), np.zeros((4, 4, 4), dtype=np.uint8),
                   np.zeros((4,), dtype=np.uint8)]
        with patch.object(rapid, '_build_engine') as build:
            self.assertEqual(recognizer.recognize_many([]), [])
            for image in invalid:
                with self.subTest(image_type=type(image), shape=getattr(image, 'shape', None)):
                    with self.assertRaises((TypeError, ValueError)):
                        recognizer.recognize(image)
            with self.assertRaises(TypeError):
                recognizer.recognize_many(self.image)
            with self.assertRaises(ValueError):
                recognizer.recognize_many([], color_order='rgba')
            build.assert_not_called()

    def test_configuration_validation(self):
        for kwargs in ({'num_threads': 0}, {'batch_size': True}, {'batch_size': 1.5},
                       {'model_dir': 'a', 'model_path': 'b'}, {'allow_download': 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                RapidOCRRecognizer(**kwargs)

    def test_failed_initialization_can_retry(self):
        engine = lambda request: SimpleNamespace(txts=['OK'], scores=[.9])
        recognizer = RapidOCRRecognizer()
        with patch.object(rapid, '_build_engine', side_effect=[OSError('load failed'), (engine, SimpleNamespace)]) as build:
            with self.assertRaisesRegex(OSError, 'load failed'):
                recognizer.warmup()
            self.assertEqual(recognizer.recognize(self.image).text, 'OK')
            recognizer.warmup()
            self.assertEqual(build.call_count, 2)

    def test_inference_error_releases_lock_and_keeps_model(self):
        from unittest.mock import Mock
        engine = Mock(side_effect=[RuntimeError('inference failed'), SimpleNamespace(txts=['OK'], scores=[.9])])
        recognizer = RapidOCRRecognizer()
        with patch.object(rapid, '_build_engine', return_value=(engine, SimpleNamespace)) as build:
            with self.assertRaisesRegex(RuntimeError, 'inference failed'):
                recognizer.recognize(self.image)
            self.assertTrue(recognizer._lock.acquire(blocking=False))
            recognizer._lock.release()
            self.assertEqual(recognizer.recognize(self.image).text, 'OK')
            build.assert_called_once()

    def test_empty_model_output_and_invalid_results(self):
        for output in (None, SimpleNamespace(txts=None)):
            with patch.object(rapid, '_build_engine', return_value=(lambda request: output, SimpleNamespace)):
                self.assertEqual(RapidOCRRecognizer().recognize(self.image), OCRResult('', 0))
        invalid = [SimpleNamespace(txts=[], scores=[]), SimpleNamespace(txts=[None], scores=[.9]),
                   SimpleNamespace(txts=['X'], scores=[float('nan')]),
                   SimpleNamespace(txts=['X'], scores=[1.1])]
        for output in invalid:
            with self.subTest(output=output), patch.object(rapid, '_build_engine', return_value=(lambda request: output, SimpleNamespace)):
                with self.assertRaises(RuntimeError):
                    RapidOCRRecognizer().recognize(self.image)

    def test_offline_missing_or_invalid_model_fails_before_import(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                RapidOCRRecognizer(model_dir=directory, allow_download=False).warmup()
            path = Path(directory) / rapid.MODEL_FILENAME
            path.write_bytes(b'not the model')
            for kwargs in ({'model_path': path}, {'model_dir': directory}):
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    RapidOCRRecognizer(**kwargs).warmup()
            self.assertEqual(path.read_bytes(), b'not the model')

    def test_missing_or_changed_rapidocr_has_actionable_error(self):
        from importlib.metadata import PackageNotFoundError
        with TemporaryDirectory() as directory:
            with patch('importlib.metadata.version', side_effect=PackageNotFoundError('rapidocr')):
                with self.assertRaisesRegex(ImportError, 'pip install -r requirements-ocr.txt'):
                    RapidOCRRecognizer(model_dir=directory).warmup()
            with patch('importlib.metadata.version', return_value='0.0.0'):
                with self.assertRaisesRegex(RuntimeError, 'Expected rapidocr==3.9.2'):
                    RapidOCRRecognizer(model_dir=directory).warmup()

    def test_ddr_preparation_preserves_original_color(self):
        image = np.full((20, 40, 3), (20, 80, 30), dtype=np.uint8)
        image[8:12, 16:22] = 240
        original = image.copy()
        prepared = prepare_ddr_crop(image)
        self.assertEqual(prepared.shape, (40, 52, 3))
        self.assertTrue(np.any(prepared[:, :, 0] != prepared[:, :, 1]))
        np.testing.assert_array_equal(image, original)
        np.testing.assert_array_equal(prepared, prepare_ddr_crop(image[:, :, ::-1], color_order='rgb'))


@unittest.skipUnless(os.environ.get('DDRCV_TEST_OCR_MODEL'), 'Set DDRCV_TEST_OCR_MODEL for offline real-model tests')
class RapidOCRModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        root = Path(__file__).resolve().parents[1]
        frame = cv2.imread(str(root / 'state_images/song_splash_updated.png'))
        if frame is None:
            raise RuntimeError('Missing tracked DDR screenshot')
        cls.crops = [prepare_ddr_crop(frame[463:497, 62:273]),
                     prepare_ddr_crop(frame[463:497, 1006:1218])]
        cls.ocr = RapidOCRRecognizer(model_path=os.environ['DDRCV_TEST_OCR_MODEL'], allow_download=False)
        # Network must remain unnecessary with a provisioned model.
        with patch('socket.socket.connect', side_effect=AssertionError('Unexpected network access')):
            cls.ocr.warmup()

    def test_real_batch_order_across_internal_batch_boundary(self):
        crops = self.crops * 4  # eight crops; default internal batch size is six
        self.assertEqual([r.text for r in self.ocr.recognize_many(crops)], ['ZERO.', 'PLAYER2'] * 4)

    def test_real_shared_instance_threads(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.ocr.recognize, self.crops * 3))
        self.assertEqual([r.text for r in results], ['ZERO.', 'PLAYER2'] * 3)

    def test_real_rgb_and_gray(self):
        import cv2
        self.assertEqual(self.ocr.recognize(self.crops[0][:, :, ::-1], color_order='rgb').text, 'ZERO.')
        gray = cv2.cvtColor(self.crops[1], cv2.COLOR_BGR2GRAY)
        self.assertEqual(self.ocr.recognize(gray).text, 'PLAYER2')

    def test_real_results_name_and_scores(self):
        import cv2
        root = Path(__file__).resolve().parents[1]
        frame = cv2.imread(str(root / 'state_images/results_updated.png'))
        self.assertIsNotNone(frame)
        crops = [frame[88:117, 816:1039], frame[348:401, 797:1039],
                 frame[592:614, 1002:1066]]
        results = self.ocr.recognize_many(map(prepare_ddr_crop, crops))
        self.assertEqual([result.text for result in results], ['N.NATURE', '999,760', '1851'])


if __name__ == '__main__':
    unittest.main()

"""Package metadata/data contract, including installed-wheel verification.

Run this file with the wheel's interpreter from outside the source checkout to
ensure imports and assets do not accidentally come from an editable install.
"""
from importlib import metadata, resources
from pathlib import Path
import unittest


class PackagingTests(unittest.TestCase):
    def test_installed_dependency_metadata(self):
        package = metadata.metadata('ddrcv')
        self.assertEqual(package['Requires-Python'], '<3.13,>=3.12')
        self.assertEqual(set(package.get_all('Provides-Extra')),
                         {'ocr', 'tournament', 'workbench', 'desktop', 'jacket-lookup'})
        requirements = metadata.requires('ddrcv')
        self.assertTrue(any(r.startswith('onnxruntime==1.30.0') for r in requirements))
        self.assertTrue(any(r.startswith('ddrcv[workbench]') for r in requirements))

    def test_launch_entry_points(self):
        entries = {entry.name: entry.value for entry in metadata.distribution('ddrcv').entry_points}
        self.assertEqual(entries['ddrcv-desktop'], 'ddrcv.desktop.__main__:main')
        self.assertEqual(entries['ddrcv-workbench'], 'ddrcv.workbench.__main__:main')

    def test_installed_assets(self):
        for package, glob in [('ddrcv.desktop', 'templates/*.html'),
                              ('ddrcv.desktop', 'static/*'),
                              ('ddrcv.workbench', 'templates/*.html'),
                              ('ddrcv.workbench', 'static/*'),
                              ('ddrcv.jacket_lookup', 'assets/*.json'),
                              ('ddrcv.jacket_lookup', 'assets/templates/*.png'),
                              ('ddrcv.state', 'world/*.pkl'),
                              ('ddrcv.state', 'data/*.pkl'),
                              ('ddrcv.score', 'fonts/World2/*.png')]:
            with self.subTest(package=package, glob=glob):
                self.assertTrue(list(Path(str(resources.files(package))).glob(glob)))
        for name in ('splash_p1.png', 'splash_p2.png'):
            self.assertTrue(resources.files('ddrcv.ocr').joinpath('fixtures', name).is_file())

    def test_installed_recognition_templates_load(self):
        from ddrcv.apps.driver_config import normalize_config
        from ddrcv.state.world_states import StateRotation
        from ddrcv.score.score_extractor import ScoreExtractor
        StateRotation(**normalize_config({})['state'])
        ScoreExtractor(None)
        from ddrcv.jacket_lookup.assets import PACKAGE_ASSETS, profile, legacy_profile, qualified_profile
        from ddrcv.jacket_lookup.difficulty import DifficultyTemplates
        self.assertEqual(len(DifficultyTemplates(PACKAGE_ASSETS / 'templates').templates), 5)
        self.assertEqual(profile()['score'], .4)
        for frozen in (profile(), legacy_profile()):
            self.assertEqual(qualified_profile(frozen['gallery_fingerprint']), frozen)
        self.assertEqual(profile()['equivalent_to'], legacy_profile()['gallery_fingerprint'])


if __name__ == '__main__':
    unittest.main()

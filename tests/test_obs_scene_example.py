"""Example-only OBS setup and real-feed wiring; no OBS installation required."""
from copy import deepcopy
from pathlib import Path
import runpy
import socket
import tempfile
import time
from types import SimpleNamespace as NS
import unittest


EXAMPLE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'examples/obs_scene_switching/demo.py'))
COLLECTION, SCENES = EXAMPLE['COLLECTION'], EXAMPLE['SCENES']


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('Timed out waiting for example state')
        time.sleep(.02)


class FakeOBS:
    def __init__(self):
        self.collection = 'Original'
        self.collections = ['Original']
        self.scenes = set(SCENES.values())
        self.scene = SCENES['lobby']
        self.inputs = {}
        self.items = {}
        self.transforms = {}
        self.active = False
        self.switches = []
        self.refreshes = []

    def get_output_list(self):
        return NS(outputs=[dict(outputName='recording', outputActive=self.active)])
    def get_scene_collection_list(self):
        return NS(scene_collections=list(self.collections), current_scene_collection_name=self.collection)
    def create_scene_collection(self, name):
        self.collections.append(name)
        self.collection = name
        self.scenes = {'Scene'}
    def set_current_scene_collection(self, name): self.collection = name
    def get_video_settings(self): return NS(base_width=1920, base_height=1080)
    def get_scene_list(self): return NS(scenes=[{'sceneName': name} for name in self.scenes])
    def create_scene(self, name): self.scenes.add(name)
    def get_input_list(self):
        return NS(inputs=[dict(inputName=name, inputKind=value['kind']) for name, value in self.inputs.items()])
    def create_input(self, scene, name, kind, settings, enabled):
        self.inputs[name] = dict(kind=kind, settings=settings)
        return self.create_scene_item(scene, name, enabled)
    def create_scene_item(self, scene, name, enabled):
        self.items[(scene, name)] = len(self.items) + 1
        return NS(scene_item_id=self.items[(scene, name)])
    def get_scene_item_list(self, scene):
        return NS(scene_items=[dict(sourceName=name, sceneItemId=i) for (s, name), i in self.items.items() if s == scene])
    def set_input_settings(self, name, settings, overlay): self.inputs[name]['settings'] = settings
    def press_input_properties_button(self, name, button): self.refreshes.append((name, button))
    def set_scene_item_enabled(self, scene, item_id, enabled): pass
    def set_scene_item_transform(self, scene, item_id, transform): self.transforms[scene] = transform
    def get_current_program_scene(self): return NS(current_program_scene_name=self.scene)
    def set_current_program_scene(self, name):
        self.scene = name
        self.switches.append(name)
    def disconnect(self): pass


class SetupTests(unittest.TestCase):
    def test_setup_creates_dedicated_collection_and_is_idempotent(self):
        client = FakeOBS()
        with tempfile.TemporaryDirectory() as tmp:
            first = EXAMPLE['setup'](client, tmp, 'ws://127.0.0.1:9020')
            second = EXAMPLE['setup'](client, tmp, 'ws://127.0.0.1:9021')
            self.assertEqual(first['previous_collection'], 'Original')
            self.assertEqual(second['collection'], COLLECTION)
            self.assertEqual(client.collections, ['Original', COLLECTION])
            self.assertEqual(len(client.inputs), 3)
            self.assertEqual(len(client.items), 3)
            self.assertEqual(len(client.refreshes), 6)
            self.assertIn('Scene', client.scenes)
            for key, scene in SCENES.items():
                page = (Path(tmp) / f'{key}.html').read_text(encoding='utf-8')
                self.assertNotIn('{{', page)
                self.assertIn('overlay/index.html', page)
                self.assertEqual(client.transforms[scene]['boundsWidth'], 1920)
            self.assertIn('9021', (Path(tmp) / 'overlay/index.html').read_text(encoding='utf-8'))

    def test_setup_refuses_active_output_without_changes(self):
        client = FakeOBS()
        client.active = True
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'active OBS'):
                EXAMPLE['setup'](client, tmp)
            self.assertEqual(client.collection, 'Original')
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_setup_repairs_missing_item_and_preserves_other_source(self):
        client = FakeOBS()
        with tempfile.TemporaryDirectory() as tmp:
            EXAMPLE['setup'](client, tmp)
            client.items.pop((SCENES['gameplay'], SCENES['gameplay'] + ' card'))
            client.inputs['Operator source'] = dict(kind='image_source', settings={})
            EXAMPLE['setup'](client, tmp)
            self.assertEqual(len(client.items), 3)
            self.assertIn('Operator source', client.inputs)

    def test_simulation_snapshots_preserve_results_and_reset_next_song(self):
        class Publisher:
            def send_message(self, message): self.message = deepcopy(message)
        publisher = Publisher()
        producer = EXAMPLE['DemoState'](publisher)
        self.assertIsNone(publisher.message['score'])
        producer.set('song_playing')
        producer.score(0, 1200)
        producer.set('song_result')
        self.assertEqual(publisher.message['score'], dict(p1_score=0, p2_score=1200))
        self.assertEqual(publisher.message['player_names'], dict(p1='ALICE', p2='BOB'))
        producer.set('unknown')
        self.assertEqual(publisher.message['score']['p2_score'], 1200)
        producer.set('song_select')
        self.assertIsNone(publisher.message['score'])
        with self.assertRaises(ValueError): producer.score(1, 2)
        with self.assertRaises(ValueError): producer.set('invalid')


class FeedTests(unittest.TestCase):
    def setUp(self):
        from ddrcv.publish.websocket_publisher import WebSocketPublisher
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.publisher = WebSocketPublisher(host='127.0.0.1', port=port, delay=.02)
        self.publisher.start()
        self.producer = EXAMPLE['DemoState'](self.publisher)
        self.client = FakeOBS()
        self.client.collection = COLLECTION
        self.follower = EXAMPLE['StateFollower'](self.client, f'ws://127.0.0.1:{port}')
        self.follower.start()
        wait_for(lambda: self.follower.latest.get('state') == 'song_select')

    def tearDown(self):
        self.follower.close()
        self.publisher.stop()
        self.assertFalse(self.follower.thread.is_alive())

    def test_real_feed_transitions_hold_manual_override_and_resume(self):
        self.producer.set('song_playing')
        wait_for(lambda: self.client.scene == SCENES['gameplay'])
        self.producer.set('song_result')
        wait_for(lambda: self.client.scene == SCENES['results'])
        for state in ('unknown', 'future_state'):
            self.publisher.send_message({'state': state})
            wait_for(lambda: self.follower.latest.get('state') == state)
            self.assertEqual(self.client.scene, SCENES['results'])
        self.follower.service.manual_scene(SCENES['lobby'])
        self.producer.set('song_playing')
        wait_for(lambda: self.follower.latest.get('state') == 'song_playing')
        self.assertEqual(self.client.scene, SCENES['lobby'])
        self.follower.service.automate(True)
        wait_for(lambda: self.client.scene == SCENES['gameplay'])

    def test_disconnect_reconnect_and_invalid_envelopes(self):
        self.producer.set('song_playing')
        wait_for(lambda: self.client.scene == SCENES['gameplay'])
        self.publisher.send_message('invalid envelope')
        time.sleep(.15)
        self.assertEqual(self.follower.latest['state'], 'song_playing')
        self.publisher.stop()
        wait_for(lambda: not self.follower.connected)
        self.assertEqual(self.client.scene, SCENES['gameplay'])
        self.producer.set('song_result')
        self.publisher.start()
        wait_for(lambda: self.client.scene == SCENES['results'])
        self.assertIsNone(self.follower.error)

    def test_collection_change_stops_the_follower(self):
        self.client.collection = 'Operator collection'
        wait_for(self.follower.stop.is_set)
        self.assertIn('scene collection', self.follower.error)
        self.assertEqual(self.client.scene, SCENES['lobby'])


if __name__ == '__main__':
    unittest.main()

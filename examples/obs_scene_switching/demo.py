"""Create an OBS scene collection and demonstrate DDRCV state-driven switching."""
import argparse
from copy import deepcopy
import getpass
from html import escape
import json
import os
from pathlib import Path
import runpy
import threading
import time

from ddrcv.publish.obs_policy import ScenePolicy
from ddrcv.publish.obs_service import OBSService
from ddrcv.publish.websocket_publisher import WebSocketPublisher


HERE = Path(__file__).resolve().parent
COLLECTION = 'DDRCV State Demo'
SCENES = {name: f'DDRCV Demo - {name.title()}' for name in ('lobby', 'gameplay', 'results')}
SCENE_MAP = {
    'unknown': None,
    'login': SCENES['lobby'],
    'song_select': SCENES['lobby'],
    'song_splash': SCENES['gameplay'],
    'song_playing': SCENES['gameplay'],
    'song_result': SCENES['results'],
    'total_result': SCENES['lobby'],
}
STATES = tuple(SCENE_MAP)
DEFAULT_ASSETS = HERE.parents[1] / '.workbench' / 'obs-scene-example'
DEFAULT_FEED = 'ws://127.0.0.1:9010'


def require_idle(client):
    # Query existing outputs: GetReplayBufferStatus errors when it is disabled.
    for output in client.get_output_list().outputs:
        if output['outputActive']:
            raise ValueError(f"Stop the active OBS {output['outputName']} output before running this demo.")


def require_collection(client):
    if client.get_scene_collection_list().current_scene_collection_name != COLLECTION:
        raise ValueError(f'Select the {COLLECTION!r} scene collection in OBS first.')


def write_assets(directory, feed_url):
    directory = Path(directory).resolve()
    prepare = runpy.run_path(str(HERE.parent / 'browser_overlay' / 'prepare.py'))['prepare_overlay']
    prepare(directory / 'overlay', feed_url)
    template = (HERE / 'scene.html').read_text(encoding='utf-8')
    colors = {'lobby': '#89b4ff', 'gameplay': '#75e5bc', 'results': '#ffba82'}
    descriptions = {
        'lobby': 'Players sign in, select a song, or finish the set.',
        'gameplay': 'Song splash and live gameplay share this scene.',
        'results': 'The song has ended. Last accepted gameplay scores remain visible.',
    }
    for key, scene in SCENES.items():
        states = ' / '.join(state for state, target in SCENE_MAP.items() if target == scene)
        page = template.replace('{{TITLE}}', key.title()).replace('{{COLOR}}', colors[key])
        page = page.replace('{{STATES}}', escape(states)).replace('{{DESCRIPTION}}', descriptions[key])
        (directory / f'{key}.html').write_text(page, encoding='utf-8')
    # Paste this map into desktop Advanced configuration when using real capture.
    (directory / 'scene_map.json').write_text(json.dumps(SCENE_MAP, indent=2) + '\n', encoding='utf-8')
    return directory


def setup(client, directory=DEFAULT_ASSETS, feed_url=DEFAULT_FEED):
    """Create/update only this example's named sources in its own collection."""
    require_idle(client)
    collections = client.get_scene_collection_list()
    previous = collections.current_scene_collection_name
    if COLLECTION not in collections.scene_collections:
        client.create_scene_collection(COLLECTION)
    elif previous != COLLECTION:
        client.set_current_scene_collection(COLLECTION)
    require_collection(client)
    directory = write_assets(directory, feed_url)
    video = client.get_video_settings()
    scenes = {item['sceneName'] for item in client.get_scene_list().scenes}
    inputs = {item['inputName']: item for item in client.get_input_list().inputs}
    for key, scene in SCENES.items():
        if scene not in scenes:
            client.create_scene(scene)
        source = scene + ' card'
        settings = dict(is_local_file=True, local_file=str(directory / f'{key}.html'),
                        width=1280, height=720, fps=30, shutdown=False, restart_when_active=False)
        if source not in inputs:
            item_id = client.create_input(scene, source, 'browser_source', settings, True).scene_item_id
        else:
            if inputs[source]['inputKind'] != 'browser_source':
                raise ValueError(f'{source!r} already exists and is not a browser source.')
            client.set_input_settings(source, settings, True)
            items = client.get_scene_item_list(scene).scene_items
            existing = next((item for item in items if item['sourceName'] == source), None)
            item_id = existing['sceneItemId'] if existing else client.create_scene_item(scene, source, True).scene_item_id
        client.set_scene_item_enabled(scene, item_id, True)
        client.set_scene_item_transform(scene, item_id, dict(positionX=0, positionY=0,
            alignment=5, boundsType='OBS_BOUNDS_SCALE_INNER', boundsAlignment=0,
            boundsWidth=video.base_width, boundsHeight=video.base_height))
        # The local path stays constant, so setting the same settings won't reload it.
        client.press_input_properties_button(source, 'refreshnocache')
    client.set_current_program_scene(SCENES['lobby'])
    return dict(collection=COLLECTION, previous_collection=previous, assets=str(directory), feed_url=feed_url)


class DemoState:
    """Small simulated producer. Every send is a complete documented snapshot."""
    def __init__(self, publisher):
        self.publisher = publisher
        self.message = {}
        self.set('song_select')

    def set(self, state):
        if state not in STATES:
            raise ValueError('Unknown demo state')
        score = self.message.get('score') if state in ('song_result', 'unknown') else None
        if state == 'song_playing':
            score = dict(p1_score=0, p2_score=0)
        self.message = dict(state=state, players=[True, True], song=None, score=score,
                            player_names=dict(p1='ALICE', p2='BOB'))
        self.publish()

    def score(self, p1, p2):
        if self.message['state'] != 'song_playing':
            raise ValueError('Select song_playing before setting scores')
        if any(type(value) is not int or value < 0 for value in (p1, p2)):
            raise ValueError('Scores must be nonnegative integers')
        self.message['score'] = dict(p1_score=p1, p2_score=p2)
        self.publish()

    def publish(self):
        self.publisher.send_message(deepcopy(self.message))


class StateFollower:
    """Consume the actual feed, then apply DDRCV's shared OBS scene policy."""
    def __init__(self, client, feed_url):
        self.service = OBSService(client=client, policy=ScenePolicy(SCENE_MAP))
        self.feed_url = feed_url
        self.stop = threading.Event()
        self.thread = None
        self.connected = False
        self.error = None
        self.latest = {}

    def start(self):
        require_idle(self.service.client)
        require_collection(self.service.client)
        self.service.automate(True)
        self.thread = threading.Thread(target=self._run, name='example-state-follower', daemon=True)
        self.thread.start()

    def _apply(self):
        with self.service.lock:
            # A collection change ends the demo; never steer another collection.
            require_collection(self.service.client)
            self.service.update(self.latest)
            if self.service.status['error']:
                raise RuntimeError(self.service.status['error'])

    def _run(self):
        from websockets.sync.client import connect
        from websockets.exceptions import WebSocketException
        while not self.stop.is_set():
            try:
                with connect(self.feed_url, open_timeout=2, close_timeout=1) as websocket:
                    self.connected = True
                    self.error = None
                    self.latest = {}  # A reconnect must receive a new snapshot.
                    while not self.stop.is_set():
                        try:
                            raw = websocket.recv(timeout=.25)
                        except TimeoutError:
                            self._apply()
                            continue
                        try:
                            message = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(message, dict) or not isinstance(message.get('state'), str):
                            continue
                        self.latest = message
                        self._apply()
            except (OSError, TimeoutError, WebSocketException) as error:
                self.error = f'Feed disconnected ({type(error).__name__}); retrying'
            except Exception as error:
                self.error = str(error)
                self.stop.set()
            finally:
                self.connected = False
            self.stop.wait(.5)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.service.disconnect()

    def status(self):
        return dict(feed_connected=self.connected, state=self.latest.get('state', 'waiting'),
                    **self.service.status, follower_error=self.error)


def cycle(producer, seconds=3):
    for state in ('login', 'song_select', 'song_splash', 'song_playing', 'song_result', 'unknown', 'total_result'):
        print(f'Publishing {state} -> {SCENE_MAP[state] or "hold current scene"}', flush=True)
        producer.set(state)
        for i in range(10):
            if state == 'song_playing':
                producer.score((i + 1) * 123, (i + 1) * 120)
            time.sleep(seconds / 10)


def console(follower, producer=None):
    print('Commands: status | manual lobby/gameplay/results | auto | quit')
    if producer:
        print('Simulation: cycle | scores 1234 1200 | ' + ' | '.join(STATES))
    while not follower.stop.is_set():
        try:
            parts = input('demo> ').strip().split()
        except EOFError:
            break
        if not parts:
            continue
        try:
            if parts == ['quit']:
                break
            elif parts == ['status']:
                print(json.dumps(follower.status(), indent=2))
            elif parts == ['auto']:
                follower.service.automate(True)
            elif len(parts) == 2 and parts[0] == 'manual' and parts[1] in SCENES:
                with follower.service.lock:
                    require_collection(follower.service.client)
                    follower.service.manual_scene(SCENES[parts[1]])
            elif producer and parts == ['cycle']:
                cycle(producer)
            elif producer and len(parts) == 3 and parts[0] == 'scores':
                producer.score(int(parts[1]), int(parts[2]))
            elif producer and len(parts) == 1 and parts[0] in STATES:
                producer.set(parts[0])
            else:
                print('Unknown command; use status or quit.')
        except ValueError as error:
            print(error)
    if follower.error:
        print(follower.error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('setup', 'simulate', 'follow'))
    parser.add_argument('--host', default='127.0.0.1', help='OBS host')
    parser.add_argument('--port', type=int, default=4455, help='OBS WebSocket port')
    parser.add_argument('--feed', default=DEFAULT_FEED, help='State feed URL for setup/follow')
    parser.add_argument('--feed-port', type=int, default=9010, help='Local simulated feed port')
    parser.add_argument('--assets', type=Path, default=DEFAULT_ASSETS)
    parser.add_argument('--cycle', action='store_true', help='Simulate one automatic cycle, then exit')
    args = parser.parse_args()
    from obsws_python import ReqClient
    password = os.environ.get('OBS_WEBSOCKET_PASSWORD')
    if password is None:
        password = getpass.getpass('OBS WebSocket password (blank if authentication is disabled): ')
    client = ReqClient(host=args.host, port=args.port, password=password, timeout=5)
    follower = publisher = None
    try:
        if args.command == 'setup':
            print(json.dumps(setup(client, args.assets, args.feed), indent=2))
            return
        feed = f'ws://127.0.0.1:{args.feed_port}' if args.command == 'simulate' else args.feed
        follower = StateFollower(client, feed)
        if args.command == 'simulate':
            publisher = WebSocketPublisher(host='127.0.0.1', port=args.feed_port, delay=.05)
            publisher.start()
            producer = DemoState(publisher)
        else:
            producer = None
        follower.start()
        if args.cycle and producer:
            cycle(producer)
        else:
            console(follower, producer)
        if follower.error and follower.stop.is_set():
            raise RuntimeError(follower.error)
    finally:
        if follower:
            follower.close()
        else:
            client.disconnect()
        if publisher:
            publisher.stop()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass

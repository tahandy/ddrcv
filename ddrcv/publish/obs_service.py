"""OBS connection and policy shared by desk and rehearsal controls."""
import threading

from ddrcv.publish.obs_policy import ScenePolicy


class OBSService:
    def __init__(self, client=None, policy=None):
        self.lock = threading.RLock()
        self.client = client
        self.policy = policy or ScenePolicy()
        self.enabled = False
        self.error = None
        self.scenes = []
        self.actual = None
        self.missing = []

    def connect(self, host='localhost', port=4455, password='', scene_map=None):
        from obsws_python import ReqClient
        with self.lock:
            self.disconnect()
            self.policy = ScenePolicy(scene_map)
            try:
                self.client = ReqClient(host=host, port=int(port), password=password, timeout=2)
                self.validate()
            except Exception as error:
                self.error = f'OBS connection failed: {error}'
                self.disconnect()
                raise ValueError(self.error) from error
            return self.status

    def validate(self):
        with self.lock:
            if self.client is None:
                raise ValueError('Connect OBS first')
            self.scenes = [item['sceneName'] for item in self.client.get_scene_list().scenes]
            self.missing = sorted({name for name in self.policy.scene_map.values() if name and name not in self.scenes})
            self.actual = self.client.get_current_program_scene().current_program_scene_name
            self.error = 'Missing OBS scenes: ' + ', '.join(self.missing) if self.missing else None
            return self.status

    @property
    def status(self):
        with self.lock:
            return dict(connected=self.client is not None, automation=self.enabled,
                        actual_scene=self.actual, scenes=list(self.scenes), missing=list(self.missing),
                        error=self.error or self.policy.last_error, scene_map=dict(self.policy.scene_map))

    def automate(self, enabled):
        with self.lock:
            if enabled:
                self.validate()
                if self.missing:
                    raise ValueError(self.error)
            self.enabled = bool(enabled)

    def update(self, message, enabled=None):
        with self.lock:
            if self.client is None:
                return
            if enabled is not None:
                self.enabled = enabled
            self.policy({}, message, self.client, override=not self.enabled)
            try:
                self.actual = self.client.get_current_program_scene().current_program_scene_name
                self.error = 'Missing OBS scenes: ' + ', '.join(self.missing) if self.missing else None
            except Exception as error:
                self.error = str(error)

    def manual_scene(self, name):
        with self.lock:
            self.enabled = False
            if self.client is None:
                raise ValueError('Connect OBS first')
            self.client.set_current_program_scene(name)
            self.actual = name

    def disconnect(self):
        with self.lock:
            self.enabled = False
            if self.client is not None:
                try:
                    self.client.disconnect()
                except Exception:
                    pass
            self.client = None

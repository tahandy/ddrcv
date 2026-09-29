"""Real runtime plus local WebSocket latency on repeated recorded splash frames."""
from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import socket
import threading
import time

for key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):
    os.environ[key]='1'

from websockets.sync.client import connect
from ddrcv.apps.driver_ddr import create_runtime
from ddrcv.apps.driver_config import validate_config
from ddrcv.jacket_lookup.images import read_image
from .benchmark import metrics
from .catalog import read_json,dump_json

ROOT=Path('experiments/jacket_lookup/artifacts')
OUT=ROOT/'integration'


class Source:
    def __init__(self,frame):
        self.frame=frame
        self.gate=threading.Event()
        self.first=None
        self.deadline=0
    def start(self): pass
    def stop(self): pass
    def get_frame(self):
        if not self.gate.is_set():return None
        now=time.perf_counter()
        if now<self.deadline:
            time.sleep(min(.01,self.deadline-now))
            return None
        if self.first is None:self.first=now
        self.deadline=now+1/30
        return self.frame


def wait(predicate):
    until=time.monotonic()+10
    while not predicate():
        if time.monotonic()>until:raise TimeoutError('Runtime not ready')
        time.sleep(.005)


def main():
    rows=[]
    manifest=read_json(ROOT/'corpus/manifest.json')
    for entry in (r for r in manifest['samples'] if r['kind']=='clean'):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        image=ROOT/'corpus'/entry['image']
        config=validate_config(dict(ingest=dict(image=dict(path=str(image))),
            results=dict(enabled=False),player_names=dict(enabled=True),
            song_lookup=dict(enabled=True,assets_dir=str(OUT/'assets')),
            publish=dict(websocket=dict(host='127.0.0.1',port=port,delay=.1))))
        runtime=create_runtime(config,logging.getLogger('wire-validation'),desktop=True)
        runtime.fetcher.stop()
        runtime.fetcher=source=Source(read_image(image))
        runtime.start()
        try:
            wait(lambda:runtime.splash is not None and runtime.splash.names.ready)
            with connect('ws://127.0.0.1:'+str(port),open_timeout=5) as client:
                source.gate.set()
                observed={}
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    message=json.loads(client.recv(timeout=2))
                    elapsed=(time.perf_counter()-source.first)*1000 if source.first is not None else 0
                    if message['state']=='song_splash':observed.setdefault('state_ms',elapsed)
                    if message.get('song'):
                        observed.setdefault('song_ms',elapsed)
                        if all(message['song']['charts'].values()):observed.setdefault('charts_ms',elapsed)
                    if all(message.get('player_names',{}).values()) and message.get('player_names'):
                        observed.setdefault('names_ms',elapsed)
                    if all(k in observed for k in ('state_ms','song_ms','charts_ms','names_ms')):
                        break
                if len(observed)!=4:raise AssertionError(observed)
                rows.append(dict(id=entry['id'],**observed,message=message,
                                 frame_processing_ms=metrics([v*1000 for _,v in runtime.processing_times])))
        finally:runtime.stop()
    result=dict(protocol='Real TournamentRuntime and WebSocket at 100ms polling; warm OCR before first frame; each clean recorded frame repeated at approximately 30fps. Timing demonstration, not independent accuracy evidence.',
                rows=rows,summary={key:metrics([r[key] for r in rows]) for key in ('state_ms','song_ms','charts_ms','names_ms')})
    dump_json(OUT/'wire.json',result);print(result['summary'])


if __name__=='__main__':main()

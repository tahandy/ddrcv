"""Reproduce the MKV acceptance run. Never sends to Discord.

python -B tools/replay_results.py --video ... --model ...
"""
import argparse
from copy import deepcopy
import json
import logging
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ddrcv.apps import driver_ddr as driver
from ddrcv.ingest.file_source import FileSource
from ddrcv.workbench.controller import Workbench
from ddrcv.results.service import ResultsService


def assert_record(records):
    assert len(records)==1, f'Expected one event, got {len(records)}'
    r=records[0]
    assert [p['name'] for p in r['players']]==['XETA','DANOOCT1'],r
    assert [p['score'] for p in r['players']]==[1615,1632],r
    assert r['outcome']==dict(kind='winner',winner=1,margin=17),r
    assert not r['partial'] and r['screenshot_confirmed'],r
    assert r['delivery']['state']=='saved',r
    return r


class WindowSource(FileSource):
    def __init__(self,path,start,end):
        super().__init__(path)
        self.seek(start)
        self.end_seconds=end

    def read(self):
        if self.index / self.fps >= self.end_seconds:
            self.ended=True
            return None
        return super().read()


class RecordingPublisher:
    def __init__(self):self.messages=[]
    def start(self):pass
    def stop(self):pass
    def send_message(self,message):self.messages.append(deepcopy(message))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--output',default='.workbench/validation')
    parser.add_argument('--start',type=float,default=255)
    parser.add_argument('--end',type=float,default=278)
    args=parser.parse_args()
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    config=dict(enabled=True,discord=False,rehearsal=True,
                ocr=dict(model_path=str(Path(args.model).resolve()),allow_download=False))
    cli_out=output/'cli'
    if list(cli_out.glob('*/result.json')) or (output/'workbench/results').exists():
        raise SystemExit('Choose a fresh --output directory so both integrations exercise OCR.')
    services=[]
    def make_service(*a,**kw):
        service=ResultsService(*a,**kw);services.append(service);return service
    publisher=RecordingPublisher()
    source=WindowSource(args.video,args.start,args.end)
    settings=dict(ingest={'video':{'path':args.video}},state={},score_extractor={'glyph_dir':None},
                  publish={},results={**config,'outbox_directory':str(cli_out)},score_mode='ex',
                  driver_debug={'render_frame':False})
    began=time.perf_counter()
    with patch.object(driver,'create_frame_fetcher',return_value=source),patch.object(driver,'create_publisher',return_value=publisher),patch.object(driver,'ResultsService',side_effect=make_service):
        driver.main(settings,logging.getLogger('replay-cli'))
    cli=assert_record(services[0].status()['records'])
    gameplay_scores = [message['score'] for message in publisher.messages
                       if message.get('state') == 'song_playing' and message.get('score')]
    cli_elapsed=time.perf_counter()-began
    assert len(publisher.messages)>=int((args.end-args.start)*source.fps)
    wb_dir=output/'workbench';wb_dir.mkdir(exist_ok=True)
    (wb_dir/'results_config.json').write_text(json.dumps(config),encoding='utf-8')
    wb=Workbench(wb_dir,start_publisher=False)
    try:
        wb.submit('score_mode',mode='ex')
        wb.submit('open',kind='video',path=args.video)
        wb.submit('seek',seconds=args.start)
        wb.submit('playback',speed=2)
        wb.submit('play')
        deadline=time.monotonic()+60
        while wb.status()['position']<args.end and time.monotonic()<deadline:
            time.sleep(.05)
        wb.submit('pause')
        assert wb.results.flush(5)
        workbench=assert_record(wb.results.status()['records'])
        # Delivering a status callback while paused must update the feed immediately.
        assert wb.status()['published']['results']['latest']['event_id']==workbench['event_id']
        # A second pass through the same interval must not produce another event.
        wb.submit('seek',seconds=264)
        wb.submit('play')
        deadline=time.monotonic()+10
        while wb.status()['position']<267 and time.monotonic()<deadline:time.sleep(.05)
        wb.submit('pause');wb.results.flush(5)
        assert len(wb.results.status()['records'])==1
        assert wb.results.status()['deduplicated']>=1
        status=wb.status()
        from ddrcv.workbench.app import create_app
        client=create_app(wb).test_client()
        assert client.get('/').status_code==200
        screenshot=client.get(f"/api/results/{workbench['event_id']}/screenshot")
        assert screenshot.status_code==200
        assert screenshot.mimetype=='image/png'
        screenshot.close()
    finally:wb.close()
    summary=dict(video=str(Path(args.video).resolve()),window=[args.start,args.end],
                 cli=dict(event_id=cli['event_id'],timestamp=cli['timestamp'],elapsed=cli_elapsed,
                          messages=len(publisher.messages),screenshot=cli['screenshot_path'],
                          last_gameplay_scores=gameplay_scores[-1] if gameplay_scores else None),
                 workbench=dict(event_id=workbench['event_id'],timestamp=workbench['timestamp'],
                     screenshot=workbench['screenshot_path'],deduplicated=status['results']['deduplicated']),
                 players=cli['players'],outcome=cli['outcome'])
    (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    main()

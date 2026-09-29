"""Summarize retained measurements and independently check raw metadata scores."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'artifacts/integration'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def metrics(values):
    values = sorted(values)
    def percentile(p):
        position = (len(values)-1)*p
        index = int(position)
        return values[index] + (values[min(index+1,len(values)-1)]-values[index])*(position-index)
    return dict(n=len(values), median=percentile(.5), p95=percentile(.95),
                p99=percentile(.99), maximum=values[-1]) if values else None


def main():
    profile = read(ROOT.parents[1]/'ddrcv/jacket_lookup/assets/gallery.json')
    source = ROOT/'artifacts/catalog/cache'/profile['source_commit']/'src/songs'
    world = read(source/'ddr_world.json')['songs']
    event = read(source/'dia_del_ritmo_26.json')['songs']
    labels = read(ROOT/'ground_truth.json')['labels']
    replay = read(OUT/'replay.json')
    assert len(replay['videos']) == 7, 'Wait for all seven replay files to finish'
    chart_checks = []
    for video in replay['videos']:
        for observation in video['observations']:
            label = labels[observation['expected_id']]
            song = observation['snapshot']['song']
            assert song['song_id'] == label['song_id']
            for player, manual in label['players'].items():
                actual = song['charts'][player]
                dataset = 'ddr_world' if observation['mode'] == 'full' else 'dia_del_ritmo_26'
                def find(rows):
                    return [c for row in rows if 'sa:'+row.get('saHash','') == label['song_id']
                            for c in row['charts'] if (c['style'],c['diffClass'],c['lvl']) ==
                            ('single',manual['difficulty'],manual['level'])]
                charts = find(world if dataset == 'ddr_world' else event)
                values = {c.get('maxScore') for c in charts}
                assert len(values) <= 1, (label, dataset, values)
                expected = next(iter(values)) if values else None
                origin = dataset if expected is not None else None
                if charts and expected is None and dataset != 'ddr_world':
                    supplemental = {c.get('maxScore') for c in find(world)}
                    if len(supplemental) == 1:
                        expected = next(iter(supplemental))
                        origin = 'ddr_world' if expected is not None else None
                expected_status = 'matched' if expected is not None else 'missing_max_ex' if charts else 'chart_outside_pool'
                expected_provenance = dict(dataset=origin, commit=profile['source_commit'] if charts else None)
                correct = (actual['difficulty'] == manual['difficulty'] and actual['max_ex'] == expected
                           and actual['status'] == expected_status and actual['provenance'] == expected_provenance
                           and actual['level'] == (manual['level'] if charts else None))
                chart_checks.append(dict(mode=observation['mode'], sample=observation['expected_id'],
                    player=player, difficulty=manual['difficulty'], expected_max_ex=expected,
                    actual_max_ex=actual['max_ex'], status=actual['status'], correct=correct))
                assert correct, chart_checks[-1]
    runs = [read(OUT/f'paced-{i}.json') for i in (1,2,3)]
    samples = [s for run in runs for s in run['samples']]
    videos = [dict(file=v['video'],decoded_frames=v['decoded_frames'],expected_splashes=v['expected_splashes'])
              for v in replay['videos']]
    mode_summary = {}
    for mode in ('event','full'):
        rows = [o for v in replay['videos'] for o in v['observations'] if o['mode']==mode]
        charts = [c for c in chart_checks if c['mode']==mode]
        mode_summary[mode] = dict(song_events=len(rows), song_correct=sum(o['song_correct'] for o in rows),
            difficulties_correct=sum(sum(o['difficulty_correct'].values()) for o in rows),
            chart_results=len(charts), max_ex_and_provenance_correct=sum(c['correct'] for c in charts),
            available_max_ex=sum(c['actual_max_ex'] is not None for c in charts),
            unavailable_max_ex=sum(c['actual_max_ex'] is None for c in charts))
    test_log = (OUT/'all-tests.log').read_text(encoding='utf-8',errors='replace')
    test_count = int(re.search(r'Ran (\d+) tests', test_log).group(1))
    skipped = int(re.search(r'OK \(skipped=(\d+)\)', test_log).group(1))
    result = dict(schema=1, measured_date='2026-09-29',
        environment=dict(os='Windows x64',cpu='Intel Core i9-14900HX',python='CPython 3.12',
                         cpu_only=True,native_threads=1,high_qos=True,names='two persistent OCR instances'),
        profile=profile, parity=read(OUT/'parity.json'),
        performance=dict(protocol='Three fresh processes, 11 clean images, warmup then three passes at 5 Hz per process',
            distinct_images=11, pooled={k:metrics([s[k] for s in samples]) for k in ('total_ms','chart_ms')},
            stages={k:metrics([s['stages'][k] for s in samples]) for k in samples[0]['stages']},
            runs=[{k:r[k] for k in ('init_ms','initial_rss','warm_rss','mean_cpu_cores','summary','enqueue_ms','confirmation_ms')}
                  for r in runs],
            replaced_jobs=sum(max(e['status']['replaced'] for e in r['episodes']) for r in runs),
            replaced_name_samples=(sum(max(e['names_status']['replaced_samples'] for e in r['episodes'])
                                       for r in runs) if all('names_status' in e for r in runs for e in r['episodes']) else None),
            errors=[e['status']['error'] for r in runs for e in r['episodes'] if e['status']['error']],
            websocket=read(OUT/'wire.json')['summary']),
        replay=dict(protocol=replay['protocol'],videos=videos,
            decoded_frames=sum(v['decoded_frames'] for v in videos),
            distinct_song_events=sum(v['expected_splashes'] for v in videos),
            modes=mode_summary,chart_checks=chart_checks),
        installation=read(OUT/'installation.json'),browser=read(OUT/'browser.json'),
        tests=dict(total=test_count,optional_skipped=skipped,real_ocr_tests=17,powershell_assertions=25),
        limits=['Six held-out song groups; repeated frames and perturbations are not independent evidence.',
                'No held-out Challenge difficulty examples and no held-out eligible-event max-EX positive.',
                'One eligible Dia chart among the 22 replayed player charts.',
                'Video replay decodes all frames but evaluates the recognition engine at 10 Hz and drains splash/login jobs.',
                'WebSocket latency uses recorded stable frames at 30 Hz after warmup; no physical capture rehearsal.',
                'Portable fingerprint equivalence tested on Windows on this host; other architectures are unqualified.'])
    result['performance']['targets'] = dict(complete_p95_under_50_ms=all(r['summary']['total_ms']['p95'] < 50 for r in runs),
        enqueue_p95_under_3_ms=all(r['enqueue_ms']['p95'] < 3 for r in runs))
    result['performance']['gallery_bytes'] = sum(p.stat().st_size for p in (OUT/'assets/galleries'/profile['gallery_fingerprint']).rglob('*') if p.is_file())
    path = ROOT/'integration_measured_summary.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_report(result)
    print(json.dumps(dict(pooled=result['performance']['pooled'],modes=mode_summary,
                         frames=result['replay']['decoded_frames'],chart_checks=len(chart_checks)),indent=2))


def write_report(result):
    perf = result['performance']
    runs = perf['runs']
    def trio(row):
        return ' / '.join(f"{row[k]:.2f}" for k in ('median','p95','p99'))
    table = '\n'.join(f"| {i} | {trio(r['summary']['total_ms'])} | {trio(r['enqueue_ms'])} | {r['init_ms']:.0f} | {r['mean_cpu_cores']:.3f} |"
                      for i,r in enumerate(runs,1))
    stages = '\n'.join(f"| {label} | {trio(perf['stages'][key])} |" for key,label in
                       [('encode','Jacket descriptor'),('search','Exact search'),('verify','Correlation verification'),
                        ('difficulty','Both difficulty templates'),('splash_total','Concurrent jacket + chart path')])
    rss = '–'.join(f"{v/2**20:.1f}" for v in (min(r['warm_rss'] for r in runs),max(r['warm_rss'] for r in runs)))
    init = '–'.join(f"{v/1000:.2f}" for v in (min(r['init_ms'] for r in runs),max(r['init_ms'] for r in runs)))
    wire = perf['websocket']
    targets = 'met' if all(perf['targets'].values()) else 'NOT met (see individual run values)'
    increment = metrics([r['warm_rss']-r['initial_rss'] for r in runs])['median']/2**20
    text = f"""# Packaged CPU splash recognition — integration evidence

Measured 2026-09-29 on Windows x64, Intel Core i9-14900HX, CPython 3.12.
See [machine-readable results](integration_measured_summary.json) and the
[operator guide](../../doc/song_recognition.md).

## Outcome and scope

The classical matcher, difficulty templates, catalog selection, and persistent
parallel workers now live in ddrcv/jacket_lookup. The desktop, DDR World CLI, and
workbench share SplashService. Experimental encoders, SIFT, and benchmark code
remain in this experiment; production never imports experiments.

Song recognition remains disabled by default. The working settings are Dia Del
Ritmo 2026, Singles, templates, one OCR instance per player, one native thread per
instance, and HighQoS. Difficulty OCR is an explicit alternative. Names retain
their independent enable setting and three-sample / 400 ms confirmation policy.
Renderer layouts, Results delivery, and Discord integration were not changed.

The CPU targets were {targets} in all three fresh-process runs: warm complete parsing
p95 below 50 ms and enqueue p95 below 3 ms. Observed clean coverage and accepted
precision meet the requested targets on this corpus, but the small held-out set
cannot establish a population-level 95% guarantee. Live capture remains untested.

## Matching and metadata boundaries

Every production event searches the same 1,577-artwork calibrated full DDR gallery.
The event selects eligible charts afterward. The matcher retains 128-pixel
references, all 16 shortlisted candidates, the same correlation window and
80% grayscale / 20% color weighting, distinct-song margins, and score/margin
thresholds of 0.40 / 0.28. The five packaged difficulty templates retain their
0.56 / 0.02 thresholds and original crop provenance.

Gallery source: {result['profile']['source_commit']}.
Portable gallery fingerprint: {result['profile']['gallery_fingerprint']}.
The original index artifact checksum is retained in the packaged gallery profile.
A fresh source rebuild matches the fingerprint; moving cache paths or changing
build timings does not change it. Identity order, artwork bytes, feature arrays,
and algorithm settings remain bound to the profile. Array/file checksums are
verified separately. Other CPU architectures have not been qualified.

Explicit preparation pins event and WORLD metadata to one immutable revision and
caches referenced artwork checksums, including WORLD aliases at new paths. It
rejects conflicting stable identifiers, reports unsupported artwork/identities,
and blocks newly shared artwork. Stored maxScore is preserved; only exact,
unambiguous song/style/difficulty/level matches can supplement missing scores.
The tested latest upstream revision resolved to the same pinned commit. A real
second event, first_step_26, prepared successfully; cross-revision conflicts,
new aliases, missing scores, and overrides are covered by fixtures.

Runtime loading is offline. Bundles are validated before atomic activation,
refreshes do not mutate a running session, and failed preflight leaves the current
runtime intact. Template-only lookup works in a wheel-installed environment with
neither RapidOCR nor ONNX Runtime. No Torch or FAISS is imported by production.
The legacy jacket package and dependent obsolete demos were retired; existing
untracked caches and historical evidence were preserved.

## Accuracy and parity

The frozen pre-integration implementation was retained independently under the
ignored artifacts/integration/baseline directory. Across full and event indexes,
284 jacket comparisons and 108 splash comparisons had **zero output differences**,
including candidates, scores, rejection reasons, difficulty, chart selection,
max EX, and provenance. Maximum observed score difference was 0.0. Thresholds were
not recalibrated. Event-only indexes remain experimental; their parity checks do
not imply that production uses an event-only visual index.

The held-out full-gallery checks contain six clean song groups: 6/6 correct
accepted matches, top-1 and top-5 both 6/6, and zero false accepts. Six non-splash
negatives and six controls with the correct song/all variants removed produced
zero accepts. Of 12 transition observations, seven were labelled identifiable;
six matched correctly and one abstained. All 42 synthetic perturbations matched
correctly. These perturbations and repeated video frames are correlated evidence,
not additional independent song groups. For scale, 6/6 independent successes
would have a two-sided 95% exact-binomial lower bound of only about 54%.

All seven original TBD5 recordings were decoded: {result['replay']['decoded_frames']:,} frames,
11 song appearances, and 22 visible player charts. The overlapping trim was
excluded. Two recordings contained no labelled splash. Each selection produced
11/11 correct songs and 22/22 correct difficulties, with no extra confirmed song
events. Full mode returned all 22 expected WORLD max-EX values. Dia mode returned
one eligible value (Mesmerizer P2 Expert: 1881) and 21 unavailable out-of-pool
results. All 44 chart outcomes across the two selections were checked against
manual difficulty/level labels and the original pinned source JSON, including
score provenance. Running the same footage against two selections does not double
the independent sample count.

Replay processes the recognition engine at 10 Hz while decoding every frame and
drains workers during eligible splash/login samples. It verifies source-time
confirmation and lifecycle behavior; it is not a wall-clock latency measurement.
There are no held-out Challenge examples and no held-out eligible-event max-EX
positive. Name OCR timing uses the real models, but this replay does not establish
new, independently labelled name accuracy. Existing name policy and real-model
fixtures remain covered.

## CPU timing

Three fresh processes, fixed native thread counts of one, HighQoS, both names
enabled, full-gallery search, templates, warmup, then three passes over 11 clean
frames at 5 Hz per process. There are 99 timed observations from 11 distinct
images. Timings below are median / p95 / p99 in milliseconds.

| Process | Complete parsing | Capture-side enqueue | Initialization ms | Mean logical cores |
| --- | --- | --- | --- | --- |
{table}

Pooled complete parsing: **{trio(perf['pooled']['total_ms'])} ms**. Enqueue includes
the service's copy/submission work; no recognition result is cached across frames.
Branches stop once their fields confirm. The measured name/chart service episodes
had {perf['replaced_jobs']} replaced chart jobs and {len(perf['errors'])} errors. Unit tests deliberately
block workers and verify one active job plus one replaceable pending job, stale
completion rejection, and bounded shutdown. Recorded name-service replacements:
{perf['replaced_name_samples']} (null means the counter was not recorded in every run).

| Concurrent stage | Median / p95 / p99 ms |
| --- | --- |
{stages}

Stages overlap, so their times must not be summed. Total parsing includes both OCR
name readers. Initialization, including gallery verification and OCR warmup, was
{init} s. Warm process working set was {rss} MiB (about {increment:.1f} MiB above the initial
process with query images loaded). The gallery occupies about {perf['gallery_bytes']/2**20:.1f} MiB on disk;
raw source catalogs/jackets, OCR model, and retained validation artifacts are
additional cache storage. CPU use above is process CPU seconds divided by elapsed
paced seconds, expressed as logical cores, not percent of the entire machine.

## Confirmation and WebSocket delivery

Song and each player's difficulty require two matching accepted samples at least
200 ms apart. Names require three matching reads spanning 400 ms. Rejections,
conflicts, gaps above 750 ms, fades, resets, seeks, and source changes are tested.
A completion from the first in-flight sample after a fade is also rejected.
Confirmed fields persist through gameplay and per-song results; absent or
unconfirmed charts remain null. Background changes publish without a new frame.

A separate test used the real TournamentRuntime, RecognitionEngine, publisher,
and WebSocket client. Each of the 11 stable recorded frames was repeated at about
30 Hz after model warmup. From the first delivered frame to client receipt:

| Published field | Median / p95 / p99 ms |
| --- | --- |
| Confirmed splash state | {trio(wire['state_ms'])} |
| Song and both charts | {trio(wire['charts_ms'])} |
| Both names | {trio(wire['names_ms'])} |

This includes state debounce, temporal confirmation, and the publisher's 100 ms
broadcast interval. The approximately half-second chart result and later name
result are distinct from the tens-of-milliseconds single-frame parsing cost.
The controlled source does not include physical capture-card buffering or an OBS
rehearsal, and is not an independent recognition-accuracy dataset.

## Validation and reproduction

The complete Python suite passes: {result['tests']['total']} tests, with
{result['tests']['optional_skipped']} optional skips in the main environment. The
separate real-OCR run passes all 17 tests, including its four model-dependent
cases, with offline warmup enforced. The PowerShell setup suite passes 25 assertions.

Disposable Windows venv checks cover fresh and repeated locked/inexact sync,
adding the optional extra to an existing environment, preserving an unrelated
sentinel package, wheel installation outside the checkout, packaged templates,
and offline template lookup without OCR dependencies. Headless Edge checks of
both real app surfaces pass readiness, enable/apply behavior, settings, and
song/max-EX rendering with no browser errors. The UI status examples are seeded
from measured recognition results; they are not live hardware evidence.

Reproduction from the checkout (raw data remains outside tracked source):

    python -m experiments.jacket_lookup.integration_validation parity
    python -m experiments.jacket_lookup.integration_validation replay --videos D:/TBD5
    python -m experiments.jacket_lookup.integration_validation paced --output experiments/jacket_lookup/artifacts/integration/paced-1.json
    python -m experiments.jacket_lookup.integration_wire
    python -m experiments.jacket_lookup.integration_install
    python -m experiments.jacket_lookup.integration_ui
    python -m experiments.jacket_lookup.integration_report

Run paced measurements in three separate processes and choose paced-1.json,
paced-2.json, and paced-3.json respectively. Installation validation expects a
built wheel in artifacts/integration/dist. UI validation uses Playwright only in
the disposable test environment. The parity command needs the retained frozen
baseline, original catalog/index artifacts, and labelled corpus. The summary
builder independently rechecks every replayed chart against raw source metadata.

Raw logs, per-sample JSON, the source backup, setup venvs, screenshots, and the
frozen baseline live in ignored artifacts/integration. The tracked summary and
this report preserve the measurements without committing those large assets.
"""
    (ROOT/'INTEGRATION_REPORT.md').write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()

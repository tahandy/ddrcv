# Packaged CPU splash recognition — integration evidence

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

The CPU targets were met in all three fresh-process runs: warm complete parsing
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

Gallery source: c62053faa82df55ebc926812a7af684f520ae704.
Portable gallery fingerprint: 31d166b1936794dbc69e718a4e28de85dfe5887c7d67635c48cf77c495e45d1d.
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

All seven original TBD5 recordings were decoded: 84,360 frames,
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
| 1 | 30.70 / 34.79 / 38.14 | 0.32 / 1.88 / 2.23 | 1484 | 0.352 |
| 2 | 30.16 / 36.04 / 37.06 | 0.40 / 1.91 / 2.05 | 1414 | 0.335 |
| 3 | 20.68 / 31.19 / 33.59 | 0.31 / 1.41 / 1.68 | 1333 | 0.269 |

Pooled complete parsing: **28.20 / 34.90 / 37.45 ms**. Enqueue includes
the service's copy/submission work; no recognition result is cached across frames.
Branches stop once their fields confirm. The measured name/chart service episodes
had 0 replaced chart jobs and 0 errors. Unit tests deliberately
block workers and verify one active job plus one replaceable pending job, stale
completion rejection, and bounded shutdown. Recorded name-service replacements:
0 (null means the counter was not recorded in every run).

| Concurrent stage | Median / p95 / p99 ms |
| --- | --- |
| Jacket descriptor | 2.26 / 3.97 / 4.82 |
| Exact search | 1.16 / 2.29 / 2.67 |
| Correlation verification | 10.40 / 14.93 / 16.22 |
| Both difficulty templates | 3.98 / 7.42 / 8.02 |
| Concurrent jacket + chart path | 15.22 / 21.78 / 22.66 |

Stages overlap, so their times must not be summed. Total parsing includes both OCR
name readers. Initialization, including gallery verification and OCR warmup, was
1.33–1.48 s. Warm process working set was 312.0–312.6 MiB (about 241.0 MiB above the initial
process with query images loaded). The gallery occupies about 105.4 MiB on disk;
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
| Confirmed splash state | 310.48 / 341.69 / 342.04 |
| Song and both charts | 527.32 / 560.67 / 561.69 |
| Both names | 751.43 / 810.17 / 834.90 |

This includes state debounce, temporal confirmation, and the publisher's 100 ms
broadcast interval. The approximately half-second chart result and later name
result are distinct from the tens-of-milliseconds single-frame parsing cost.
The controlled source does not include physical capture-card buffering or an OBS
rehearsal, and is not an independent recognition-accuracy dataset.

## Validation and reproduction

The complete Python suite passes: 365 tests, with
12 optional skips in the main environment. The
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


## Portable catalog follow-up (2026-09-29)

The runtime now reads a single ZIP-based `.ddrcatalog` directly, with no extraction
or new dependency. Each file carries the full qualified gallery, selected chart
metadata, matching profile, provenance, and a checksum manifest. The loader checks
member names, sizes, checksums, array shapes/dtypes, the gallery fingerprint, and
profile compatibility. Preparation validates a temporary candidate before atomic
replacement. Old folder catalogs remain readable and convert offline; they are
not deleted. An active session retains its loaded data until Apply.

Desktop and workbench expose Catalog file and Browse in the Song recognition tab,
with revision/date information and one-file transfer instructions. Full DDR still
disables the event field. Blank file paths use the per-selection default under
`jacket_lookup/catalogs` in the user cache. Source downloads remain separate.

Container/folder comparisons show **zero differences** in 284 jacket queries and
108 splash parses across Dia and WORLD metadata selections. Both search the same
1,577-image gallery. Each selection covers 11 clean events, 22 transitions, 21
negatives, 11 removed-song controls, and 77 synthetic perturbations. Candidates,
scores, rejections, difficulties, chart selections, max EX and provenance agree
exactly after excluding timings. These are existing samples, not additional
independent recognition evidence.

| Catalog file | Size | Folder load median | Container load median |
| --- | --- | --- | --- |
| Dia Del Ritmo 2026 | 70.05 MiB | 757 ms | 1,073 ms |
| Full DDR / WORLD | 70.43 MiB | 969 ms | 1,211 ms |

Load timings use three alternating repetitions in one process, with OS file
caches warm; they include verification and template readiness, without OCR. ZIP
verification/decompression adds startup work. After loading, the algorithm and
arrays are identical. Paired warm template splash parsing (55 samples per format
per selection, alternating order, native threads fixed to one) measured:

| Selection / format | Median / p95 / p99 ms |
| --- | --- |
| Dia / folder | 7.49 / 8.24 / 10.59 |
| Dia / container | 7.49 / 8.89 / 10.64 |
| WORLD / folder | 7.59 / 8.43 / 8.57 |
| WORLD / container | 7.56 / 8.30 / 8.40 |

These timings exclude name OCR and temporal confirmation; the earlier complete
parsing and WebSocket measurements above remain separate. Raw working-set deltas
are recorded but are allocator-sensitive, not peak-memory estimates.

A transfer check copied only the Dia file into an empty temporary directory,
blocked networking and access to the original catalog, and recovered max EX 1881.
No files were extracted and no source cache was created. Refreshing this copy
against the cached pinned upstream revision reused the embedded gallery, produced
identical selected metadata, and left the existing loaded instance unchanged.

Validation: 381 Python tests pass (12 optional skips), including 11 new archive
cases. Tests cover corruption, extra/duplicate/missing entries, incompatible
profiles, unsafe array dimensions/dtypes, explicit-file mismatch, atomic failure,
offline folder conversion, and active-session isolation. Real locked/inexact
installation checks pass repeat installs, adding the extra to existing venvs,
preserving an unrelated sentinel package, wheel loading outside the checkout, and
base-only offline template lookup without OCR. Headless Edge checks against the
installed wheel pass both file-selection paths, metadata display, readiness,
method toggling, and workbench activation. Native picker returns are stubbed for
these browser tests. Screenshots were visually inspected. No new live hardware
rehearsal was performed.

Reproduce container parity/transfer after the original integration artifacts exist:

    python -m experiments.jacket_lookup.catalog_container_validation

The small [container summary](container_measured_summary.json) preserves results;
per-query outputs and large files remain under ignored `artifacts/integration`.
The [operator documentation](../../doc/song_recognition.md) covers file sharing
and offline conversion with the packaged `pack` command.


## Review fixes: portable builds and recovery (2026-09-29)
The three reproduced review findings are fixed. Fresh gallery builds now use
`color-gradient-portable-v1`, with fixed normalization reduction order and wide
intermediates for color means, grayscale conversion and Sobel operations. This
removes the measured BLAS/OpenCV dispatch dependence. Its separately qualified
fingerprint is `06cbc412e6c88e53f39aef09f6c840ad237da2f5cc6e95084feb26c1030e8d33`.
The original `31d166b1…` profile and encoder remain supported: old containers and
folder bundles load, pack and refresh without changing their gallery. All profile
and artifact checks remain strict; score 0.4 and distinct-song margin 0.28 are
unchanged.

All 1,577 gallery images produce identical fingerprints in four builds: Haswell
BLAS, Sandy Bridge BLAS, unoptimized OpenCV, and unoptimized OpenCV with NumPy
AVX/AVX2/FMA3/F16C dispatch disabled. These are dispatch selections on the same
Windows x64 i9-14900HX, using locked NumPy 2.2.0 and OpenCV 4.10.0, not tests on
four physical CPUs. Fresh production preparation under Sandy Bridge also passes
from an empty build cache using only the pinned source cache, with networking
blocked.

Across the existing Dia and WORLD selections, 284 jacket queries and 108 splash
parses have identical candidates/order, acceptance/rejection, correlation scores,
margins, difficulties, selected charts, max EX and provenance. Each selection
includes 11 clean events, 22 transitions, 21 negatives, 11 removed-song controls
and 77 synthetic perturbations. The only compared output differences are the
expected profile identity/provenance and descriptor similarities (maximum
absolute delta 3.5763e-7, within the existing 1e-6 tolerance). Reference vector
components differ from the original by at most 5.0292e-8. This is equivalence on
the existing evidence, not additional independent recognition evidence.

Paired warm parsing uses 110 samples per profile/selection, alternating order,
one native thread, HighQoS and the same clean frames:

| Selection / profile | Median / p95 / p99 ms |
| --- | --- |
| Dia / legacy | 7.30 / 9.68 / 10.65 |
| Dia / portable | 7.43 / 9.86 / 10.59 |
| WORLD / legacy | 7.29 / 8.35 / 10.49 |
| WORLD / portable | 7.30 / 8.28 / 13.52 |

These are jacket plus difficulty-template splash timings, excluding name OCR and
temporal confirmation. Median encoding overhead is about 0.11 ms; the measured
full parsing tails include OS scheduling noise. No complete two-name parsing or
live capture performance claim is added by this check.

Downloads now publish through a temporary file and atomic replacement. Files
left without a committed checksum by process termination are refetched;
previously verified checksum mismatches still fail closed. Regression checks
terminate a real preparation subprocess between download publication and
checksum-manifest publication, then verify successful retry and offline reuse.
An injected publication failure also preserves the previous file.

Closing a splash service clears confirmed values and exposes closed status even
if a child worker is blocked. Failed Workbench Apply immediately clears song,
chart and name snapshots on both the wire and diagnostics, retains every worker
for later cleanup, and allows scoring to continue. Tests cover a new song
generation, late errors, no-next-frame publication, and successful Apply after
the blocked child exits.

Validation: 389 Python tests run, 12 optional skips, no failures/errors (eight
additional regression cases). Updated packaging assertions and dispatch tests
also pass. The rebuilt wheel loads both catalog versions outside the checkout,
with networking blocked, in full and base-only environments; the base-only venv
has neither OCR runtime. Both return the known eligible chart's max EX 1881.
An unrelated sentinel package survives the wheel update. No dependency or
installer changes were needed. Existing historical reports/caches are retained;
no new live capture rehearsal was performed.

Reproduce the build/parity evidence with:

    python -m experiments.jacket_lookup.portable_gallery_validation --build-all

The [review-fix summary](review_fixes_measured_summary.json) contains compact
machine-readable results. Full builds, per-query results and preparation evidence
are in ignored `artifacts/integration/review-fixes/`. Focused regressions are in
`tests/test_lookup_review_fixes.py` and `tests/test_catalog_archive.py`.

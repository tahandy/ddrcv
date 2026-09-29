# Difficulty-only template experiment

Latest speed measurements: [behavior-preserving optimization](PERFORMANCE_REPORT.md).
The earlier accuracy and timing study below is retained for comparison.

Template matching is a promising replacement for difficulty OCR on stable,
1280x720 DDR WORLD splashes. It reads only Beginner, Basic, Difficult, Expert,
or Challenge. Level digits are neither templated nor recognized.

The experiment now supports an explicit template path; broader integration is
still deferred. No desktop, live recognition, renderer or publishing code changes.

## Method and chart resolution

Five manually cropped word templates describe white lettering beside dark
outlines. An inexpensive channel-min/max mask suppresses much of the animated
colored background. OpenCV normalized cross-correlation searches each player's
existing difficulty ROI, allowing the label to occupy different horizontal
positions for P1 and P2. The best class must pass both similarity and separation
thresholds: **score >= 0.56 and margin >= 0.02**, fitted on calibration only.
These scores are similarities, not probabilities. No automatic OCR fallback is
used in this experiment.

The five mask PNGs total **2,693 bytes**; loading them took approximately **1.7 ms**
in the measured process. Provenance and frozen calibration metadata are separate.
Only existing NumPy/OpenCV/Pillow dependencies are used by the template lookup
path. A real offline event lookup was verified with RapidOCR, ONNX Runtime,
Torch, and timm imports explicitly blocked.

Chart resolution uses song identity + explicit style + difficulty within the
selected event dataset (or WORLD for full mode). Conflicting chart levels or max
EX records cause abstention, even when two different levels have the same max
EX. A returned `metadata_level` comes from the catalog; it is not an image reading.
Missing metadata and out-of-event charts still return unavailable max EX.

## Source separation and accuracy

Four songs supply templates: I'm an Albatraoz (Beginner/Basic), GUILTY DIAMONDS
(Difficult), FUTURE (Expert), and Holic (Challenge). Their eight player observations
are **template-source checks only**, never independent evaluation. Holic was
moved out of the original jacket held-out group because it is the corpus's sole
Challenge appearance. The jacket thresholds and indexes were not changed.

Two songs remain for calibration, and **five songs / ten player observations**
remain for evaluation. Templates and thresholds were frozen before those scores
were evaluated. Frozen provenance includes template checksums, ground-truth and
manifest hashes, source crops, and every corpus frame hash.

| Held-out difficulty crops | Template result | OCR baseline |
|---|---|---|
| Clean labels | 10/10 correct, no abstentions | 10/10 correct |
| Non-splash controls | 12/12 rejected | 12/12 rejected |
| Correct class removed | 10/10 rejected | Not applicable |
| Synthetic perturbations | 50/60 correct; 10 abstentions; zero wrong accepts | 60/60 correct |
| Fading entry frames | 10/10 abstentions | Not measured in this follow-up |
| Empty exit frames | 10/10 rejected | Not measured in this follow-up |

The six synthetic variants are JPEG quality 35, mild blur, color shift, 2/-1-pixel
offset, 75% resampling, and 70% brightness. **All ten synthetic abstentions were
the brightness reduction**: the absolute white/dark thresholds deliberately fail
closed when the lettering no longer satisfies the mask. Every entry transition
also abstained, including entries with human-readable but faded lettering. These
are real limitations, not successes counted toward coverage. All 22 entry and
22 exit crops across all phases were inspected and tested separately as stress
cases; none produced a wrong accepted difficulty.

Both methods produced correct difficulty/max-EX-or-unavailable results for all
ten held-out player observations in both catalogs. Checks over all eleven songs
also passed 22/22 per catalog, but include template and calibration sources.
The only eligible Dia max-EX example is still Mesmerizer P2, in calibration;
there is no held-out positive event max-EX claim.

Held-out clean classes are Beginner, Basic and Expert. Difficult has calibration
coverage; Challenge has only source checks. The five songs come from two source
recordings. They are a small, correlated capture sample, and the two players,
synthetic variants and repeated timings do not supply extra independent songs.
For perspective, even treating five songs as independent, 5/5 success has an
exact two-sided 95% lower bound of only about 48%. More footage is needed for a
broad accuracy claim, especially different brightness, scales, fonts and layouts.

## CPU timings

Windows i9-14900HX, CPU only, one OpenCV/BLAS/ORT thread. Both methods reuse their
loaded objects. Each cell below has 220 timed splash calls (20 passes over eleven
frames); method and frame order alternate to reduce run-order bias. The difficulty
stage includes both players plus parsing/chart metadata resolution. Complete
lookup also includes the splash check, jacket encoding/search/verification.

| Catalog | Method | Difficulty p50 / p95 / p99 ms | Complete p50 / p95 / p99 ms |
|---|---|---|---|
| full | template | 2.91 / 4.01 / 5.59 | 11.60 / 16.17 / 23.12 |
| full | ocr | 40.06 / 57.96 / 102.46 | 48.65 / 66.86 / 119.78 |
| event | template | 1.42 / 2.67 / 3.56 | 9.78 / 17.97 / 23.34 |
| event | ocr | 39.95 / 66.65 / 79.94 | 48.45 / 79.64 / 92.03 |

Complete p95 improves from **66.86 to 16.17 ms** for full DDR and from **79.64 to
17.97 ms** for Dia. Host timing varies: the earlier block-ordered trial measured
10-15 ms template p95 and 59-63 ms OCR p95. Both runs are retained under the ignored
artifact folder; the table uses the paired protocol, without selecting the faster
run. These are warm measurements, not fresh CLI startup or frame acquisition.

## Reproduce and inspect

The commands are in [README.md](README.md#difficulty-only-templates). Source is
[difficulty.py](difficulty.py), [difficulty_benchmark.py](difficulty_benchmark.py),
and the opt-in branch in [lookup.py](lookup.py). Concise results are tracked in
[difficulty_measured_summary.json](difficulty_measured_summary.json).

Generated evidence under `artifacts/difficulty-template/` includes the five mask
and source PNGs, immutable calibration snapshot, all per-query results, paired
latencies, initial block-timing results, offline demo output, and `examples.jpg`.
No generated templates, footage, indexes or models are tracked in Git. Existing
installation behavior is unchanged; the jacket extra still provides OCR for the
baseline and the application's other OCR uses.

Validation: 25 focused experiment tests pass, including nine new tests for label
matching, offsets/color order, ambiguity and unknowns, invalid/checksummed input,
optional imports, metadata-only levels, conflicting levels, and historical/event
chart selection. The template demonstration runs offline with OCR imports blocked.

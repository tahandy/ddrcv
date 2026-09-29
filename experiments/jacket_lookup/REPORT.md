# Jacket-to-max-EX proof of concept: findings

Latest speed measurements: [behavior-preserving optimization](PERFORMANCE_REPORT.md).
The earlier accuracy and timing study below is retained for comparison.

Follow-up: [difficulty-only template matching](DIFFICULTY_REPORT.md) reduces
complete splash latency without reading level digits. The original comparison
and its measurements below are retained.

**Recommend the 128-pixel classical color/gradient descriptor plus correlation
verification.** It met the jacket-lookup target with no false accepts in the
held-out controls, requires no learned jacket model, and uses dependencies that
DDRCV already has. This is sufficient to discuss integration, with the coverage
limits below; it is not broad live-capture qualification.

## What was built and measured

- An isolated CLI under `experiments/jacket_lookup/`, with catalog preparation,
  extraction, encoding, lookup, calibration/evaluation, readiness, and evidence
  commands. [Reproduction instructions](README.md).
- A pinned snapshot of [DDRCardDraw](https://github.com/noahm/DDRCardDraw/tree/c62053faa82df55ebc926812a7af684f520ae704):
  7,889 dataset-qualified DDR records, 1,750 song identities, and 2,091 asset paths.
  Content deduplication yields 1,577 square reference images; 508 historical
  non-square banners are inventoried but excluded from square-jacket lookup.
- Dia Del Ritmo 2026: 466 songs/jackets and 538 charts. Event defaults do not
  silently filter these records. All EX values retain their source provenance.
- Seven original TBD5 videos, totaling 46.9 minutes, yielded 11 distinct clean
  splash events, 22 transition frames, and 21 non-splash controls. The overlapping
  trimmed video was excluded. All 11 reference/query pairs and 22 player labels
  were manually inspected; no video splash was inserted into the reference index.
- Native upstream jackets commonly measure 128 or 150 pixels. Matching both
  sources at a shared resolution, then checking spatial correlation, worked well
  despite the roughly 429-pixel captured jackets.

## Method and tradeoffs

The selected pipeline area-resizes to 128 square pixels, constructs normalized
24x24 color and gradient descriptors, searches the entire float32 matrix with
NumPy, and verifies the leading 16 images using color/grayscale normalized
correlation with a small translation allowance. It merges artwork aliases before
computing the margin between distinct songs. Ambiguous shared art is rejected.

All methods were compared at 128 and 150 pixels with CPU execution and one
OpenCV/BLAS/inference thread. Five songs were used for calibration and six were
held out. The method choice, cutoffs, labels, and index hashes were frozen before
held-out evaluation. The two selected cutoffs are empirical, catalog-specific
similarity/margin thresholds, not probabilities.

MobileNetV3-Small was faster, but falsely accepted a gameplay crop as
**ルカルカ★ナイトフィーバー** in the full-catalog test at both tested sizes. The
crop was `2025-03-27_15-50-18_negative1`; cosine similarity was about 0.79 and
its runner-up margin about 0.05–0.06. That violates the precision-first objective.
SIFT and EfficientNet passed these controls but offered no observed accuracy
benefit over the smaller classical method. The EfficientNet comparison uses
its existing weights with the shared experiment preprocessing and thread limit;
it is not an end-to-end benchmark of the old scraper/FAISS code.

The final fresh-process jacket p95 was **8.20 ms for the full index** and
**8.09 ms for Dia Del Ritmo**, below the 50 ms target. Full-splash p95 including
two-player OCR was **57.66 ms / 54.84 ms** respectively; OCR dominates that path.
These are warm repeated calls. Index initialization took approximately
**0.85 s / 0.18 s**; a one-shot CLI additionally loads OCR and should not be
compared directly to the warm-query number.

## Accuracy and chart behavior

- Full-catalog held-out clean songs: **6/6 correct and accepted**, top-1/top-5
  both 100%. The five calibration songs were also correct, reported separately.
- Full-catalog held-out controls: all six non-splash crops and all six tests with
  the true identity/artwork removed were rejected. Twelve transition frames
  produced six correct accepts and six abstentions, including one abstention on
  partially visible artwork; no wrong accepts. All 42 synthetic perturbations
  of the six held-out songs matched correctly.
- Event held-out clean songs: **1/1 in-pool song accepted**, five out-of-pool
  songs rejected. Event controls and synthetic perturbations had no false accepts.
- Full splash decoding read **22/22 player difficulty/level labels** correctly.
  Full mode returned all 22 expected WORLD max-EX values. Event mode returned the
  one eligible value and withheld values for the other 21 observations. No
  incorrect EX values were emitted.
- Example: **メズマライザー (Mesmerizer)** identifies in both catalogs. Dia Del
  Ritmo returns **P2 Expert 15: max EX 1881**, while P1 Difficult 11 is outside
  the event chart pool and correctly receives no value.

Only three observed songs belong to the event catalog, and only one observed
player chart is eligible. That eligible EX example is in the calibration split;
there is no independent eligible-event-EX example in the held-out split. The
end-to-end evidence demonstrates the mechanism, not broad event coverage.

Six independent held-out songs are far too few to establish 99% population
precision: even treating them as independent Bernoulli trials, 6/6 gives an
illustrative two-sided exact 95% lower bound of only 54.1%. The footage is also
from one capture domain. Perturbations, adjacent frames, and repeated timing
calls do not increase the independent sample count.

## Installation and validation

`setup_desktop.bat -JacketLookup` (or the workbench equivalent) opts into the
experiment readiness check. `-NonInteractive` supports repeatable existing-venv
updates. The `jacket-lookup` extra reuses the existing OCR dependencies and adds
no Torch/FAISS/model-export dependency. No jacket model needs provisioning.

Validated: 16 focused offline tests, four package-contract tests, wheel/source
builds with large artifacts excluded, 25 PowerShell
setup assertions, and 28 existing menu assertions. A fresh minimal environment
installed successfully twice and completed a real offline splash lookup. The
actual desktop setup flag was exercised against the existing `.venv`: all 111
packages and their versions were preserved. The dependency-light splash loader
matched the existing detector on all 54 extracted frames. Desktop, driver,
streaming, renderer, and publishing implementations were not changed.

Large downloads, models, indexes and frames remain in ignored artifact folders.
The full index occupies about 105 MiB on disk (including retained metadata), and
the event index about 21 MiB; initial index construction measured 4.35 s and
1.16 s respectively, excluding catalog download. These are uncompressed-runtime
reference images/features suitable for a proof of concept; compact deployment
packaging is deferred.

[Machine-readable summary](measured_summary.json),
[full raw benchmark report](artifacts/benchmark/REPORT.md),
[frozen thresholds and split](artifacts/benchmark/frozen.json),
[visual event examples](artifacts/benchmark/event-examples.jpg).

## Detailed CPU measurements

CPU-only, one inference/OpenCV/BLAS thread. Configurations were chosen on five calibration songs before six held-out songs were evaluated.

| Index / method / size | Held-out known accepted | False accepts: real / synthetic | Warm p50 / p95 / p99 ms | Fresh process RSS MiB |
|---|---:|---:|---:|---:|
| full-classical-128 | 6/6 | 0 / 0 | 7.62 / 8.20 / 8.91 | 209.2 |
| full-classical-150 | 6/6 | 0 / 0 | 11.39 / 16.38 / 17.55 | 235.9 |
| full-sift-128 | 6/6 | 0 / 0 | 14.41 / 21.37 / 26.19 | 388.6 |
| full-sift-150 | 6/6 | 0 / 0 | 18.32 / 21.36 / 22.46 | 445.1 |
| full-mobilenet-128 | 6/6 | 1 / 0 | 2.96 / 3.28 / 3.73 | 226.2 |
| full-mobilenet-150 | 6/6 | 1 / 0 | 3.04 / 3.49 / 3.78 | 253.6 |
| full-efficientnet-128 | 6/6 | 0 / 0 | 19.05 / 26.30 / 34.35 | 487.0 |
| full-efficientnet-150 | 6/6 | 0 / 0 | 19.05 / 22.56 / 25.25 | 515.2 |
| event-classical-128 | 1/1 | 0 / 0 | 6.92 / 8.09 / 8.67 | 70.8 |
| event-classical-150 | 1/1 | 0 / 0 | 13.35 / 14.37 / 14.78 | 79.4 |
| event-sift-128 | 1/1 | 0 / 0 | 12.80 / 19.39 / 20.65 | 127.8 |
| event-sift-150 | 1/1 | 0 / 0 | 18.90 / 22.24 / 24.50 | 141.9 |
| event-mobilenet-128 | 1/1 | 0 / 0 | 2.83 / 3.18 / 3.51 | 97.6 |
| event-mobilenet-150 | 1/1 | 0 / 0 | 2.78 / 3.24 / 3.47 | 104.4 |
| event-efficientnet-128 | 1/1 | 0 / 0 | 18.42 / 21.44 / 30.80 | 356.4 |
| event-efficientnet-150 | 1/1 | 0 / 0 | 18.73 / 20.92 / 24.53 | 364.4 |

## Complete splash lookup

- full: 22/22 chart labels read correctly; 0 incorrect max EX values emitted. 22 eligible player-chart observations. Warm total p50/p95/p99: 46.62/57.66/67.15 ms.
- event: 22/22 chart labels read correctly; 0 incorrect max EX values emitted. 1 eligible player-chart observations. Warm total p50/p95/p99: 44.41/54.84/61.81 ms.

## Limits

- Eleven distinct songs are a small, single-capture-domain sample; six are held out. No population-level precision claim is supported.
- Only three recorded songs belong to the Dia Del Ritmo catalog, and only one recorded player chart is eligible. The held-out event split contains one known song and no eligible max-EX chart.
- Synthetic degradation, repeated timing calls, entry/exit frames and withholding tests are correlated with their parent songs. They are not additional independent songs.
- Thresholds are empirical similarity/margin cutoffs, not calibrated probabilities. Test results were not used to retune them.
- Historical non-square banners are inventoried but excluded from the square-jacket index. Album art shared by multiple identities is rejected.
- Max EX correctness means agreement with the pinned upstream chart metadata, not an independent note-count audit.
- Fresh-process RSS includes Python and imported libraries. Index initialization excludes interpreter startup; subprocess wall time also includes all timed queries.

Raw results, per-query records, frozen thresholds, split IDs, and profiles are adjacent to this report.

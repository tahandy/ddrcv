# Behavior-preserving lookup speed pass

An optional threaded follow-up is documented in [THREADING_REPORT.md](THREADING_REPORT.md).
The measurements below describe the earlier sequential speed pass.

The retained changes improve complete template lookup while preserving every
compared result, including numerical scores. Full-DDR median/p95 decreased by
**26.8% / 27.2%**; Dia Del Ritmo decreased by **13.2% / 9.7%**. OCR also benefited,
but most of its time remains in neural inference.

## What changed

- Each `Lookup` reuses one lazily initialized splash detector and one lazy default
  OCR recognizer. Explicit recognizer overrides still take precedence; template
  mode does not import OCR. No recognized song, difficulty or frame result is cached.
- A per-instance chart index resolves the selected dataset without repeated
  catalog scans. It preserves style, optional observed level, duplicate/conflicting
  records, missing values, event eligibility and source provenance. Returned
  dictionaries cannot mutate the cache.
- Jacket verification computes the cropped query grayscale once and lazily
  caches reference grayscale images. The 16-candidate shortlist, sorting/ties,
  translation window, 80/20 grayscale/color score and thresholds are unchanged.
- Difficulty masks use equivalent OpenCV channel min/max/subtraction operations
  and a reusable dilation kernel. Already-sized encoder images avoid a redundant
  resize, and empty exclusion sets avoid a catalog-wide membership loop.

No model, dependency, installer, default-method, index-format or public lookup
signature changes. The desktop and live recognition loop remain outside this work.
Caches are owned by a `Lookup` instance: treat its index/catalog data as a snapshot
and create a new instance after changing the underlying catalog or assets.

## Paired CPU measurements

Windows i9-14900HX, CPU only, one OpenCV/BLAS/ORT thread. Three rounds of twelve
passes over eleven clean splash frames give **396 calls per implementation,
method and catalog**. Baseline/optimized calls alternate on the same frame; frame,
method and catalog ordering also alternate. Both implementations use the same
already-loaded OCR recognizer, so default-model reuse does not inflate these gains.
Timing excludes file decoding, image acquisition and index initialization.

| Catalog | Difficulty | Baseline p50 / p95 / p99 ms | Optimized p50 / p95 / p99 ms | Median / p95 reduction |
|---|---|---|---|---|
| full | template | 11.56 / 18.54 / 26.30 | 8.47 / 13.50 / 19.07 | 26.8% / 27.2% |
| full | ocr | 49.26 / 75.04 / 92.98 | 46.33 / 74.33 / 90.82 | 6.0% / 0.9% |
| event | template | 9.47 / 16.31 / 20.40 | 8.22 / 14.73 / 19.52 | 13.2% / 9.7% |
| event | ocr | 46.88 / 73.75 / 94.26 | 46.01 / 69.15 / 83.86 | 1.9% / 6.2% |

Template median and p95 improved in all three rounds for both catalogs. Host load
varied across rounds, so these paired results supersede comparisons against older
absolute timings. Full OCR p95 changed by only 0.9%; that small aggregate tail
improvement should not be treated as a substantial OCR-inference speedup.

Full-catalog median jacket encode/search/verify stages changed from
0.530/0.785/6.401 ms to 0.525/0.585/6.157 ms. The two-player difficulty stage,
including metadata resolution, fell from 3.123 to 0.886 ms. Dia's corresponding
difficulty stage fell from 1.361 to 0.903 ms. Detector reuse saves work outside
those stages. Individual stage medians do not sum exactly to total medians.

## Initialization and memory tradeoff

Three fresh processes per configuration measured index initialization and warm
RSS after all eleven clean frames. Values below are process medians; RSS includes
Python, image libraries and catalog/index data, and these workers do not load OCR.

| Catalog | Init baseline / optimized | Warm RSS baseline / optimized | Added warm RSS |
|---|---|---|---|
| full | 0.804 / 0.859 s | 211.7 / 226.1 MiB | 14.4 MiB |
| event | 0.146 / 0.162 s | 73.7 / 76.2 MiB | 2.4 MiB |

After those frames, the full index cached 162 grayscale jackets (2.53 MiB), and
Dia cached 131 (2.05 MiB). If every jacket is eventually visited, grayscale storage
is bounded by the catalog: 24.64 MiB full, 7.28 MiB Dia. The full chart index holds
21,952 keys, versus 1,076 for Dia; its dictionaries account for much of the other
memory increase. The extra initialization and bounded memory buy lower warm cost.

The default OCR lifecycle was also tested separately with no explicit recognizer:
its constructor now runs once per `Lookup`, with one inference thread and offline
model loading. A three-call real-model diagnostic is retained in
`default-ocr-lifecycle.json`; its import/model-loading costs are not mixed into
warm benchmark gains. First OCR use remains cold; later calls reuse the model.

## Behavior preservation and validation

The pre-change implementation was captured before editing in a checksummed,
ignored source snapshot. Both implementations used the same existing indexes,
source footage, difficulty templates, and frozen acceptance profiles. No thresholds
were refitted. Comparisons ignore timings and permit at most 1e-6 score drift;
**the largest observed numeric difference was exactly zero**.

- 284 jacket queries across full/event catalogs: clean frames, non-splashes,
  entry/exit transitions, seven synthetic perturbations, and removed-song controls.
- 394 difficulty comparisons, including six perturbations and the correct class
  removed; all 240 underlying masks were pixel-identical.
- 480 complete splash comparisons across both catalogs and both difficulty methods,
  including raw frames and synthetic changes to both players' difficulty crops.
- 23,030 chart resolutions spanning all selected-dataset keys, with and without
  observed levels, plus missing-song controls.
- 32 focused tests passed. Seven new tests cover pixel boundaries/strides,
  encoder equivalence, metadata duplicates/conflicts/styles/versions, response
  isolation, lazy reference caching, recognizer overrides and optional OCR behavior.
- A real event lookup in the existing minimal venv passed with RapidOCR,
  ONNX Runtime, Torch and timm imports blocked. Mesmerizer P2 still returned 1881;
  the out-of-pool P1 chart remained unavailable.

These are parity checks, not new independent accuracy observations. The existing
small-corpus limits, missing independent Challenge example, and abstentions on
dim/fading labels remain unchanged. No live tournament performance claim is made.

## Reproduce

The retained local baseline is under `artifacts/performance/baseline/`. Verify the
same comparison from the repository root:

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup.performance --phase compare
.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_jacket_performance.py -v
```

`--repeats` and `--rounds` control timing sample counts. The default run writes
`parity.json`, complete `timings.json`, and `summary.json` under the ignored
`artifacts/performance/` directory. Baseline Python source is executed only from
that explicitly selected local snapshot; use trusted captures.

For a future speed pass, capture a baseline **before editing**, selecting a new
output folder with `--phase snapshot --out <directory>`. Compare with that same
`--out` afterward. Snapshot capture refuses to overwrite an existing baseline.
The historical source snapshot and detailed outputs remain local ignored artifacts;
a fresh checkout needs that snapshot to reproduce this historical comparison.
The concise outcome and provenance are tracked in
`measured_summary.json` under `performance_followup`.

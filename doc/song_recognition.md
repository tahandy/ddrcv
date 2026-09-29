# Song and chart recognition

DDRCV can identify a WORLD song splash, read each present player's difficulty,
and publish chart-specific max EX. Recognition is optional and disabled in
existing profiles. It does not change gameplay score reading, renderer layouts,
or Results/Discord delivery.

## Enable it

Run the optional setup once, including when updating an existing compatible venv:

    setup_desktop.bat -JacketLookup

The workbench installer accepts the same flag. This downloads the pinned artwork
gallery and pins the latest Dia Del Ritmo 2026 metadata. Rerunning preparation
reuses a verified existing selection; refreshing metadata is a separate action.
If preparation is interrupted, rerun it: downloads without committed checksums
are fetched again. A checksum mismatch in a previously verified file remains an
error rather than being silently trusted.

In the desktop's **Song recognition** tab, prepare the catalog,
check readiness, enable recognition, choose the game style, and use **Apply and
Restart**. The workbench has the same top-level tab; applying resets recognition.
Names keep their existing independent enable switch.

The defaults are Dia Del Ritmo 2026 (dia_del_ritmo_26), Singles, difficulty
templates, and HighQoS. Name recognition uses a persistent single-threaded OCR
model for each player. Difficulty OCR remains an explicit alternative in the
advanced settings. Player count does not select Singles or Doubles.

## Other catalogs and offline use

From the repository root or an installed package:

    python -m ddrcv.jacket_lookup prepare --event https://ddr.tools/#game-dia_del_ritmo_26
    python -m ddrcv.jacket_lookup check
    python -m ddrcv.jacket_lookup prepare --event EVENT_SLUG --refresh
    python -m ddrcv.jacket_lookup prepare --mode full
    python -m ddrcv.jacket_lookup lookup --image splash.png --splash
    python -m ddrcv.jacket_lookup lookup --image jacket.png

Use --catalog-file to choose a portable .ddrcatalog file. Without it, the selected
catalog lives under the catalogs directory in the shared cache: %LOCALAPPDATA%/ddrcv/jacket_lookup
on Windows, or $XDG_CACHE_HOME/ddrcv/jacket_lookup (normally ~/.cache/ddrcv/jacket_lookup)
on Linux. --assets-dir overrides the preparation cache (and default catalog
location). --ref pins an explicit metadata revision during preparation.
--style double selects Doubles explicitly. --difficulty-method ocr selects OCR.
The one-shot lookup command reports a single observation; the live service adds
temporal confirmation. --names additionally reads names for a full splash.

Only preparation/refresh downloads data. Capture and lookup use verified offline
bundles. A failed preparation retains the previous active bundle. An explicit
refresh prepares a new immutable selection; the running session continues using
its current one until apply/restart.

All event modes search the same calibrated full DDR artwork gallery, then check
chart membership in the selected pool. Full mode uses WORLD chart records.
Event UI level filters are not applied to the dataset. Stored maxScore is max EX;
missing values are supplemented only by an unambiguous matching WORLD chart
from the same source revision.

A new event can contain artwork or identities outside the qualified gallery.
Preparation reports these entries; their max EX stays unavailable. New or shared
artwork cannot silently become a calibrated match. Updating the artwork gallery
requires a separately qualified package/profile, independently of event refreshes.

## Catalog storage, versions, and sharing

**Catalog file** is a single ZIP-based `.ddrcatalog` file. DDRCV reads it directly;
do not extract it. It contains the calibrated full artwork gallery, encoded
vectors and reference images, selected event/WORLD chart metadata, frozen matching
profile, provenance, and checksums. Each event file includes the full gallery;
selecting an event changes chart eligibility, not the gallery searched.

Leave the field blank for the default location, which the tab displays:

    %LOCALAPPDATA%\ddrcv\jacket_lookup\catalogs\event-dia_del_ritmo_26.ddrcatalog

Full DDR uses `catalogs/full-world.ddrcatalog`. Browse selects an existing file;
you can paste a new `.ddrcatalog` path before preparing a catalog there. Downloads
and intermediate build files remain in the preparation cache separately. They are
not needed for recognition or transfer.

The **Prepared catalog** panel shows the DDRCardDraw metadata commit (linked to
its source), the dataset's recorded update date, the file's creation date, and the
separately pinned artwork-gallery commit and fingerprint. The dataset date is not
the Git commit timestamp. Older folder catalogs may lack a preparation date.

The active-session line identifies the version held by the recognition workers.
Preparation/refresh validates a complete new file before atomically replacing the
previous file. A failed build leaves the old file intact. Existing sessions keep
their loaded version until Apply and Restart. Version inspection is offline and
does not load image arrays or OCR; Check readiness validates the whole catalog.

Selecting **Full DDR / WORLD charts** disables and fades the event field. Its
value is retained for switching back to Event pool. The selection must match the
chosen file; DDRCV reports a mismatch instead of using another event's charts.

To share a catalog:

1. Finish preparation on the first machine, then copy its `.ddrcatalog` file to a
   local folder on the receiving machine.
2. Install a compatible DDRCV version using normal setup. In **Song recognition**,
   browse to the copied file and choose the matching event or Full DDR.
3. Click **Check readiness**, compare the displayed revisions, and apply.

For example:

    python -m ddrcv.jacket_lookup prepare --catalog-file C:\DDRCV-Catalogs\dia.ddrcatalog
    python -m ddrcv.jacket_lookup check --catalog-file C:\DDRCV-Catalogs\dia.ddrcatalog
    python -m ddrcv.jacket_lookup lookup --catalog-file C:\DDRCV-Catalogs\dia.ddrcatalog --image splash.png --splash

No extraction, jacket download, or re-encoding is needed on the receiving client.
No capture settings, profile secrets, or OCR models are included. Normal setup
provisions OCR separately; difficulty templates ship with DDRCV. Template lookup
alone requires no OCR runtime. Metadata refresh can reuse the gallery inside the
file and download only the required source data into the receiving client's cache.
A compatible package must recognize the same qualified gallery and matching
profile; readiness rejects incompatible or corrupt files.

New gallery builds use the qualified deterministic descriptor profile
`06cbc412…`. Existing `31d166b1…` catalogs remain supported with their original
encoder and matching thresholds. Reading, converting, or refreshing one preserves
its gallery; no rebuild or migration is required. The new build profile has the
same artwork, thresholds, and verified matching decisions, with CPU-independent
normalization and fixed intermediate precision.

Existing folder catalogs remain readable. **Prepare catalog** converts an existing
selection offline when its default file does not exist. To choose a destination:

    python -m ddrcv.jacket_lookup pack --assets-dir C:\OldCatalogFolder --catalog-file C:\DDRCV-Catalogs\dia.ddrcatalog

Use the matching `--mode full` or `--event EVENT_SLUG` for other selections.
Conversion preserves the chart revision and matching results and does not delete
the old folders. Existing `assets_dir` configuration remains supported as the
preparation-cache/legacy-folder location; `catalog_file` is the new file selector.

## What gets published

The app displays confirmed song identity, difficulty, and max EX. The WebSocket
song field is null until identity confirms, then contains song_id, title, artist,
catalog provenance, and charts.p1 / charts.p2. Each confirmed chart includes style,
difficulty, metadata-derived level, max_ex, status, and score-source provenance.
There is no level-digit recognition in template mode.

Identity and each player's difficulty require two agreeing accepted observations
at least 200 ms apart, sampled at most 5 Hz. Names retain three agreeing reads
spanning 400 ms. These confirmation intervals, state debounce, and feed delivery
are additional to the time to analyze one image. Missing one player's read does
not delay the other player.

An unconfirmed/absent chart is null. A recognized chart with unavailable max EX
has max_ex=null and a status such as chart_outside_pool, missing_max_ex,
ambiguous_chart, or unsupported_artwork. Confirmed values persist through gameplay
and per-song results; song/session resets, source changes, and seeks clear them.
Worker failures do not stop capture or scoring. If Workbench Apply reports that
recognition workers are still closing, song, chart and name output is cleared;
capture and scoring continue. Apply again after worker cleanup to activate the
selected configuration.

Max EX describes the chart, independent of the configured gameplay score units.
Never divide a Money score by max EX. See [the streaming contract](streaming_state.md).

## Compatibility and evidence

The retired EfficientNet/FAISS jacket package and its obsolete demos are not used.
Legacy jacket_database settings are discarded with a migration notice; old pickle
indexes are never loaded. Setup does not delete legacy user caches automatically.

Production classical/template matching requires the existing NumPy/OpenCV/Pillow
dependencies. Optional name/difficulty OCR reuses the supported OCR extra.
Torch, model export, and alternate encoders remain research-only.

See [integration validation](../experiments/jacket_lookup/INTEGRATION_REPORT.md)
for measured timings and accuracy limits. Recorded replay is not a live camera,
OBS, or tournament rehearsal.

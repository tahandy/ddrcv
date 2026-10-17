# Song and chart recognition

DDRCV can identify a WORLD song splash, read each present player's difficulty,
and publish chart-specific max EX. Recognition is optional and disabled in
existing profiles. It does not change gameplay score reading, renderer layouts,
or Results/Discord delivery.

For an accessible explanation of the matching process, see
[How DDRCV encodes jackets and recognizes songs](jacket_lookup_algorithm.md).

## Enable it

After normal application setup, open **Song recognition**. Both Desktop and
Workbench use **Choose → Prepare → Activate**:

1. **Choose your catalog.** Select **DDRCardDraw event pool** or **Full DDR / WORLD
   charts**. The event field accepts a DDRCardDraw slug or an event link such as
   `https://ddr.tools/#game-dia_del_ritmo_26`, available from
   [ddr.tools](https://ddr.tools/). It does not accept tournament registration
   links. The default is Dia Del Ritmo 2026; change it for another event.
   Event selection uses the complete dataset, ignoring website difficulty filters.
2. **Prepare the catalog.** **Build catalog** downloads current chart metadata,
   reuses supported artwork when available, and validates before replacing a file.
   **Load catalog…** opens an existing `.ddrcatalog` offline, detects its event or
   Full WORLD selection, and validates it. Neither action starts capture.
3. **Activate recognition.** Enable **Recognize song and max EX** and choose the
   game style. In Desktop, use **Start** in the window header to apply pending
   settings and start the selected source. While running, the header’s **Apply
   and Restart** applies pending settings and resets tracking. Workbench's **Apply / reset
   recognition** resets recognition/tracking; use **Playback and setup** to open
   a source and play the recording when needed.

Rehearse from before a song splash, then compare the confirmed song and chart
max EX with the recording. Names keep their independent enable switch.

The preparation status distinguishes **Catalog validated** from **Catalog found —
checked when activated**. The latter is expected after restarting the application:
metadata inspection does not load the full gallery or OCR. Activation validates
before use. Closing and reopening just the panel retains backend validation.
A file change or a different difficulty reader requires fresh validation.
Preparation errors are shown separately from the previous catalog's availability
and the session currently using it.

**Coverage warnings** lists affected songs/charts and reasons. A valid file does
not guarantee complete event coverage. Ordinary score capture can continue where
song identity or max EX is unavailable. Out-of-pool charts may require another
event or Full WORLD. Multiple IDs for the same title need catalog identity cleanup;
shared jackets need additional evidence to distinguish songs or variants.
Unsupported artwork needs updated artwork support.
Technical identifiers and file paths are under **Catalog version, storage and sharing**.

If a loaded file conflicts with a new event/mode, choose **Use the loaded catalog’s
selection**, or **Build this selection at its default location**. The latter
clears the custom path and prepares a separate selection while preserving the
loaded file. Changing the dropdown alone never activates or overwrites a catalog.

For command-line provisioning of the default event, the optional
`setup_desktop.bat -JacketLookup` flag remains available; Workbench setup accepts
it too. A retry reuses verified downloads. A verified cache checksum mismatch is
reported rather than silently accepted.

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

Full DDR uses `catalogs/full-world.ddrcatalog`. Load catalog selects an existing file;
you can paste a new `.ddrcatalog` path before building a catalog there. Downloads
and intermediate build files remain in the preparation cache separately. They are
not needed for recognition or transfer.

The **Catalog version, storage and sharing** section shows the DDRCardDraw metadata commit (linked to
its source), the dataset's recorded update date, the file's creation date, and the
separately pinned artwork-gallery commit and fingerprint. The dataset date is not
the Git commit timestamp. Older folder catalogs may lack a preparation date.

The active-session line identifies the version held by the recognition workers.
Preparation/refresh validates a complete new file before atomically replacing the
previous file. A failed build leaves the old file intact. Existing sessions keep
their loaded version until Apply and Restart. Version inspection is offline and
does not load image arrays or OCR. Build and Load validate the whole catalog
automatically; no separate readiness check is needed.

Selecting **Full DDR / WORLD charts** disables and fades the event field. Its
value is retained for switching back to Event pool. The selection must match the
chosen file; DDRCV reports a mismatch instead of using another event's charts.

To share a catalog:

1. Finish preparation on the first machine, then copy its `.ddrcatalog` file to a
   local folder on the receiving machine.
2. Install a compatible DDRCV version using normal setup. In **Song recognition**,
   choose **Load catalog…** and open the copied file. Its event or Full DDR selection
   is filled in automatically.
3. Wait for validation to finish, review coverage warnings, and enable recognition
   in step 3. Start/apply using the action appropriate to the application.

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

Existing folder catalogs remain readable. The CLI `prepare` command converts an
existing selection offline when its default file does not exist. The UI's
**Build catalog** instead requests current chart metadata, reuses cached artwork,
and safely replaces the catalog only after validation. To choose a destination
for an offline conversion:

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

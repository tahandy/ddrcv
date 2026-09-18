# DDRCV setup and operator slide guide

**Current guide:** [Control Room](control_room/README.md) is the selected 10-slide
version, revised after a first-time-operator read-through. Start there for the
PowerPoint, PDF, and speaker notes. The [three style comparisons](variants/README.md)
and original 21-slide first pass below remain available as earlier versions.

- [Editable PowerPoint](ddrcv_operator_guide.pptx) — 21 widescreen slides, with
  speaker notes on every slide. Text, diagrams, and tables are editable;
  application screenshots are embedded images.
- [Companion PDF](ddrcv_operator_guide.pdf) — the same slide content and layout,
  with slide bookmarks for quick navigation.
- [Speaker notes](speaker_notes.md) — instructions, caveats, and source references
  in a separate readable file.
- [Slide overview](contact_sheet.png) — all slides at a glance.

Use slides 1–16 for setup and rehearsal; slides 17–21 cover startup, recovery,
troubleshooting, shutdown, and handoff. The files can be viewed offline. Share
the PowerPoint or PDF directly; neither requires the source images alongside it.

The deck reflects the desktop interface and behavior in this repository on
18 September 2026. UI images show the real application forms in an isolated,
stopped session with example paths and no credentials. They do not claim a live
camera, OBS, renderer, or Discord rehearsal. Complete that rehearsal on the
actual tournament station.

For details, use the [operator walkthrough](../operator_walkthrough.md),
[quick reference](../operator_reference.md), and
[installation guide](../installation.md). Fill in the walkthrough's event setup
table before handing over. Keep passwords and webhook tokens out of the slides.

## Rebuild

The build scripts do not modify the application. From the repository root on
Windows, using an environment with the desktop dependencies plus Playwright:

```bat
.venv\Scripts\python.exe -B tools\capture_operator_guide.py
```

The capture script uses installed Microsoft Edge in headless mode and an
isolated temporary desktop controller. It blocks requests outside its local
server, never starts a runtime, and asserts that no page errors occurred. It
does not access the user's active desktop profile, cameras, OBS, or Discord.
If Playwright is in a separate dependency directory, supply
`--playwright-path "C:\path\to\packages"`.

Using a Python environment with `python-pptx`, `reportlab`, `Pillow`,
`pypdfium2`, and `pypdf` installed:

```bat
python -B tools\build_operator_deck.py
```

The build defaults to Segoe UI fonts in `C:\Windows\Fonts`. Override with
`--font-dir` when necessary. It writes the PPTX, PDF, notes, individual PNG
previews, contact sheet, and [validation report](validation.json) here.

The PDF is drawn from the same layout specification as the PowerPoint; it is
not an export from Microsoft PowerPoint. Checks cover element bounds, measured
text widths and allocated heights, PPTX package integrity, notes on every
slide, PDF page titles, and rendering every PDF page. Preview images are rendered
from that PDF. PowerPoint font substitution on another computer can change the
appearance; the PDF preserves the embedded fonts and reviewed layout.

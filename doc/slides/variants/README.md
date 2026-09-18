# Three revised operator-guide designs

**Selected and revised:** use the [final Control Room guide](../control_room/README.md)
for the latest operator walkthrough. The three decks below preserve the styling
comparison before the final first-time-operator review.

Each version is a complete **10-slide guide** with the same content and speaker
notes. Start with the [side-by-side preview](style_comparison.png) or the
[three-page comparison PDF](style_comparison.pdf).

| Style | PowerPoint | PDF | All slides |
| --- | --- | --- | --- |
| **A — Field manual** (recommended) | [Editable deck](a_field_manual/guide.pptx) | [PDF](a_field_manual/guide.pdf) | [Overview](a_field_manual/contact_sheet.png) |
| **B — Control room** | [Editable deck](b_control_room/guide.pptx) | [PDF](b_control_room/guide.pdf) | [Overview](b_control_room/contact_sheet.png) |
| **C — Editorial** | [Editable deck](c_editorial/guide.pptx) | [PDF](c_editorial/guide.pdf) | [Overview](c_editorial/contact_sheet.png) |

The [review](REVIEW.md) explains the first pass's problems, the 21-to-10 slide
consolidation, and each style's strengths and tradeoffs. Notes and validation
reports are also saved in each style's folder. The original 21-slide deck remains
in the parent folder for comparison.

## Rebuild

Use the document dependencies described in the [original build instructions](../README.md#rebuild).
From the repository root:

```bat
.venv\Scripts\python.exe -B tools\capture_operator_guide.py --output doc\slides\variants\assets
python -B tools\build_operator_variants.py
```

If Playwright is in a separate package directory, supply `--playwright-path` to
the capture script. The build supports `--font-dir`; it uses Windows Segoe UI,
Consolas, and Georgia by default. The app's styling is unchanged: variant styles
apply to the presentation only.

The [metrics report](review_metrics.json) records content identity and slide
checks. PDF previews use the shared layout renderer, not Microsoft PowerPoint.

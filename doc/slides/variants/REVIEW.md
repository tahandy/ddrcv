# Review and revision of the operator guide

## Assessment of the first pass

The 21-slide deck covered the right material, but followed the documentation's
section boundaries too closely. It read as a series of small reference entries
rather than a walkthrough of the operator's decisions.

| Criterion | First-pass problem | Revision |
| --- | --- | --- |
| Conciseness | Cover, architecture, prerequisites, and installation took four slides before reaching the controls. OBS connection and manual operation were separated. | Begin installation on slide 1. Combine source with score mode, display with OBS, and Discord setup with delivery recovery. |
| Information density | Many large cards held only one or two sentences. Repeated setup/check captions consumed space without advancing the workflow. | Replace oversized cards with compact steps, control/effect tables, and a results-mode comparison. Keep the operational outcome visible. |
| Ease of understanding | Full-panel images were too small for their labels to be useful. Similar-looking boxes gave prerequisites, actions, and warnings equal emphasis. | Capture relevant UI regions at larger size. Use action titles, the actual button names, distinct section headings, and one short check or limitation at the bottom. |
| Whitespace | Fixed-height cards and isolated short topics left large unused areas. Empty card interiors added distance between related instructions. | Give space to screenshots, steps, and comparison rows. Use margins and small gaps to group related information; remove large empty card interiors. |
| Presentation vs reference | Detailed behavior was spread across too many slides, while startup and shutdown repeated earlier instructions. | Use 10 slides for the operator workflow. Keep exceptions, default mappings, file behavior, and deeper troubleshooting in speaker notes and the written guides. |

The revised deck has **10 slides instead of 21**, a 52% reduction. This is a
guided setup/reference deck, so the reference tables deliberately contain more
information than a keynote-style presentation. Small captions identify the UI
images; the instructions themselves remain native, editable text.

## Revised sequence

| New slide | Operator task | First-pass material consolidated |
| --- | --- | --- |
| 1 | Install DDRCV and open the panel | 1–4: introduction, connections, prerequisites, installation |
| 2 | Select the feed and score mode | 5–7: panel orientation, source, EX/Money |
| 3 | Start and verify picture, state, scores | 8: first recognition check |
| 4 | Connect the display and OBS | 9–11: renderer, OBS connection, manual/resume |
| 5 | Choose results evidence | 12 and 14: screenshot setup and parsing choices |
| 6 | Verify Discord and recover delivery | 13 and 18: webhook setup and saved-result actions |
| 7 | Understand Save, Apply, Stop, and window close | 15 and part of 20: profile/runtime controls |
| 8 | Rehearse and repeat startup checks | 16–17: readiness and daily startup |
| 9 | Troubleshoot the failing part | 19: recovery reference |
| 10 | Hand over and shut down | 20–21: evidence, shutdown, operator handoff |

Key distinctions remain explicit: Save does not apply edits; full Apply resets
tracking during a run; Results-only Apply preserves gameplay; closing the panel
keeps capture running; a missed results screen cannot be recovered automatically.

## Three visual directions

All three variants contain the **same 10 slides, wording, and speaker notes**.
They are complete alternatives, not disconnected style samples. A content hash
check verifies identical visible copy, excluding theme/navigation labels.

| Variant | Design choices | Strength | Tradeoff |
| --- | --- | --- | --- |
| **A — Field manual** | Light background, blue action hierarchy, sans-serif headings, fine rules, lightly bordered groups. | Clearest all-purpose setup and reference guide. My recommendation. | Less distinctive than the editorial treatment. |
| **B — Control room** | Dark graphite, cyan headings, monospaced labels, persistent numbered side rail, filled table rows. | Fits a monitor beside the station; navigation remains visible. | The rail uses some horizontal space; dark pages are less economical to print. |
| **C — Editorial** | Warm paper, serif headlines, rust accents, large page numbers, open columns and hairline rules. | A more designed, workshop-oriented presentation with fewer boxes. | Softer hierarchy than the field manual; less visually similar to the application. |

Compare slides 1, 2, and 7 in the side-by-side preview: they demonstrate a setup
sequence, a screenshot-led explanation, and a dense reference table. Review a
full PDF before choosing; styling must work on the results and recovery pages too.

## Validation and limits

The build checks measured text widths/heights, element bounds, text-box
collisions, notes on every slide, PPTX package integrity, PDF page titles, and
rendering of all 30 PDF pages. It also verifies content identity between styles.
The PDFs share the measured source layout with the PowerPoints; they are not
native Microsoft PowerPoint exports. Font substitution can affect the editable
files on a different computer. The PDFs embed the fonts.

The current UI captures use a separate, stopped session with example paths and
no credentials. They do not demonstrate working hardware, OBS, or Discord.
Complete the event rehearsal on the actual station.

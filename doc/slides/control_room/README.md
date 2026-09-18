# DDRCV operator guide — Control Room

This is the selected **10-slide Control Room guide**, revised after a
first-time-operator read-through.

- [Editable PowerPoint](guide.pptx)
- [PDF guide](guide.pdf)
- [All slides at a glance](contact_sheet.png)
- [Speaker notes](speaker_notes.md)
- [Read-through findings and changes](READTHROUGH.md)

The slides give the operating steps; the notes supply detailed setup help,
examples, and explanations. Keep the [written walkthrough](../../operator_walkthrough.md)
and [operator reference](../../operator_reference.md) available for longer procedures.
The earlier [style comparisons](../variants/README.md) remain available separately.

## What changed in this pass

The guide now explains where files and connection details come from, what a
profile is, how to open the first picture, which steps are optional, the exact
integration setup order, the meaning of results settings and delivery labels,
and where to find saved evidence. It avoids relying on knowledge of the
application's internal architecture.

UI images show a stopped, isolated example session with no credentials. They
are for locating controls; they do not demonstrate a live hardware rehearsal.
The operator still needs the event's DDRCV files and game feed or recording.
Optional integrations require the organizer's renderer files/OBS scene setup
and a webhook supplied by a Discord channel administrator.

## Rebuild and validation

Using the document dependencies in the [original build instructions](../README.md#rebuild):

```bat
python -B tools\build_control_room_guide.py
```

Run from the repository root. The script reuses the layout/export engine in
`tools/build_operator_variants.py` and existing screenshots in
`doc/slides/variants/assets`. It writes only this final guide's outputs. It
does not rebuild the three comparison decks or modify the application.

The [validation report](validation.json) covers measured text bounds, text-box
collisions, slide count, embedded notes, PowerPoint package integrity, PDF
page titles, and rendering all ten pages. PDF previews are drawn from the same
layout specification, not exported through Microsoft PowerPoint. The PDF embeds
fonts; editable PowerPoint rendering can vary with installed fonts.

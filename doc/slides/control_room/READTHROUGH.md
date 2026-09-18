# First-time-operator read-through

The review assumed the reader had no knowledge of DDRCV's architecture or the
intended workflow. It followed the visible slides first, then checked whether
the notes answered the remaining setup details. This is an editorial walkthrough,
not a claim that a new operator has tested the guide on event hardware.

| Question exposed | Revision |
| --- | --- |
| Where do I obtain DDRCV, and do I type these filenames somewhere? | Slide 1 asks for the organizer's ZIP and explicitly says to extract and double-click the setup/launcher files. |
| Do I need all these other programs just to read scores? | Slides 1, 4, and 6 mark optional display/OBS/Discord steps and provide a path for scores and local screenshots only. |
| What does “profile” mean, and what if nobody gave me one? | Slide 2 explains the supplied `.json` settings file and the alternative of choosing Source manually. Slide 7 explains Save as, the suggested filename/location, and Open. |
| Does “camera” mean my webcam? What is RTSP? | Slide 2 identifies the game capture device and limits RTSP to a network URL supplied by the organizer. It gives a recording option for rehearsal without live hardware. |
| Which score mode should I choose? | Slide 2 relates EX to event scoring and Money to ordinary scoring toward 1,000,000, instead of referring to another application's defaults. |
| What is a splash screen? Why is my preview not moving? | Slide 3 defines the pre-song title screen, restores the first **View stream** click before **Refresh frame**, and states that each refresh is a new picture. |
| Are blank scores a failure? What should success look like? | Slide 3 distinguishes pre-gameplay blanks from live Accepted score readings and points to Running, Capture healthy, and comparison against the machine. |
| Where does the renderer come from, and how do I show it in OBS? | Slide 4 asks for the separate renderer folder, names Browse and Launch renderer, and specifies an OBS Window Capture source. |
| Do I connect OBS before or after applying settings or starting? | Slide 4 puts **Stop → enter settings → Apply configuration → Start** above the steps, then names Connect, Check scenes, and Enable automation. Notes explain mapping syntax and give an example. |
| What connection details go into OBS? | Slide 4 points to OBS's WebSocket settings, uses localhost for the same computer, and tells the reader to copy the port/password. Notes explain a remote host and existing scene names. |
| Does screenshot-only stop gameplay scores? Do I need Discord to save files? | Slide 5 says that the switches affect results parsing, preserves gameplay scoring, and gives a local-only path. Every row explicitly retains a screenshot. |
| What is a webhook, and where do I find it? | Slide 6 defines the channel posting link and identifies the channel administrator as its source. Notes include the administrator's creation/copy procedure. |
| Does the webhook test turn publishing on? | Slide 6 separates the real test message, enabling publishing, applying settings, and checking a complete song result. |
| Where is recovery, and why don't I see “Pending”? | Slide 6 says to expand **Recent results & recovery**, uses the real **Queued / Sending / Retrying** labels, and identifies **More recovery options → Republish** as creating another post. |
| How do I reopen a closed panel? Does Stop close the program? | Slide 7 gives the launcher filename for reopening and distinguishes Stop, window close, and Exit without the term “backend.” |
| What if the app already says Running? | Slide 8 tells the returning operator to verify the existing session rather than start another one. |
| Where are the reset buttons? What is capture-device ownership? | Slide 9 names the expandable section and replaces “ownership” with checking whether another app is using the camera. |
| What is the outbox, and where are these relative folders? | Slide 10 identifies both folders as being inside DDRCV and distinguishes screenshot copies from original results and delivery history. |

The revised slides remain at ten. Details that would crowd them—mapping JSON,
automatic launch options, late name updates, custom storage paths, and setup
failure recovery—are explained in notes and linked written guides.

## Source checks

Button labels and behavior were checked against the current desktop template,
JavaScript handlers, controller, and integration service. Those checks include
the requirement to start capture before integration commands, Save's behavior,
the first snapshot click, and the actual delivery-status/action labels.

The OBS notes point to its Tools-menu WebSocket controls, following the
[official OBS remote-control guide](https://obsproject.com/kb/remote-control-guide).
Selecting the renderer's window uses the
[official Window Capture source behavior](https://obsproject.com/kb/window-capture-sources).
The Discord administrator instructions follow its
[official webhook guide](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks).

The rendered PDF was reviewed, and the build checks all ten pages, notes, text
bounds, text collisions, and PPTX package integrity. These checks do not replace
the real station rehearsal described on slide 8.

# Login name-band negative fixtures

These are unmodified BGR pixel crops saved as PNG from the repository's existing
local recordings. Each image stacks P1 above P2: frame regions
`[190:240,212:550]` and `[190:240,646:984]`, producing a 338×100 image.

- `login_league_bands.png`: `apps/scripts/2025-03-19_16-47-45.mkv` at 2 seconds.
  The screen is recognized as login, but the bands say "In-game event now open!"
  and "The 5th WORLD LEAGUE". Neither side must produce a player name.
- `login_card_bands.png`: `apps/scripts/2025-03-27_15-43-31.mkv` at 132 seconds.
  The login screen is awaiting card confirmation; neither band contains a name.

Positive profile references remain the tracked full screenshots
`state_images/mar2025/english/vlcsnap-2025-03-19-22h20m04s788.png` and
`vlcsnap-2025-03-19-22h21m28s838.png`: ZVIDUN / EVILDAVE.

## Results thousands-separator regression

`results_obs_ex_1128_1144.png` retains only the two `EX_BOXES` score crops in an
otherwise black 1280×720 BGR frame. Source: the user-supplied OBS recording
`2026-10-17 00-09-47.mp4` at 1140 seconds. The displayed game inset
`[81:561,215:1067]` was resized to 1280×720 with OpenCV cubic interpolation
before extracting the score boxes. This reconstructs a scaled, compressed OBS
view; it is not the original capture feed.

The pinned recognition model reads these as `1.128` and `1.144` with confidence
above 0.8. Both must parse as integer EX scores 1128 and 1144, using the normal
reader preprocessing, confidence filter, and range validation.

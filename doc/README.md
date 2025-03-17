> The perfect is the enemy of the good

# Overview

The most trivial yet infuriating frustration in life is determining who is ahead in a high-level DDR tournament.
This package is the first step in removing one inconsequential problem from viewers' lives, while introducing a
whole new world of problems for tournament organizers. 

The core functionality of this package -- real-time parsing of the score from the DDR video feed -- debuted at 
[Arrows for Charity VI](http://www.arrowsforcharity.org) on December 7th, 2024. Streams of both the test and tournament 
can be found at [Dusk's Twitch channel](https://www.twitch.tv/starguardarcade). For an exemplary match that demonstrates
the purpose of this library, see [RAM vs DAYREON - Nageki no Ki](https://www.twitch.tv/videos/2320764725?t=9h33m37s).

Special thanks to Honey for the stream graphics/design, and tolerating my repeated revision requests.

DDRCV expects the Nov 2024 update to DDR World.

# What you'll find here

The `ddrcv` package contains a number of modules that attempt to address orthogonal problems:

| Module            | Purpose                                                                                           |
|-------------------|---------------------------------------------------------------------------------------------------|
| `ingest`          | Management of frame ingest from RTSP and video device streams                                     |
| `jacket_database` | Reverse image lookup to determine step counts from song jacket                                    |
| `ocr`             | Helper methods for using OCR via EasyOCR (deprecated)                                             |
| `score`           | Real-time parsing of score from a frame of the gameplay screen                                    |
| `state`           | Determination of current machine state/screen                                                     |
| `publish`         | Real-time publishing of state and state-specific data                                             |
| `misc`            | Random utilities (e.g. screenshots)                                                               |
| `discord`         | Publication of screenshot + results to a Discord channel via webhook                              |
| `diagnostics`     | Publication of logger to websocket (not rippled through codebase. See `sandbox/diagnostics_demo`) |

The top-level directory `apps` contains integrated apps:

| Module            | Purpose                                                                                                                 |
|-------------------|-------------------------------------------------------------------------------------------------------------------------|
| `driver`          | Driver application; contains logic stringing all of the above components together                                       |
| `obs`             | Flask middleman that connects to the driver websocket and controls OBS for automated scene transitions                  |
| `state_simulator` | Flask app for simulating state message publishing; used to facilitate OBS scene setup without needing to run `driver`   |

The top-level directory `sandbox` is just for one-off development testing stuff.

# What you won't find here

- The pinnacle of software engineering; I make no apologies.
- Tests; this stuff may break.
- Ground-breaking computer vision techniques; The problem domain here is extremely static (barring UI updates), and the
goal is to operate in real-time on limited hardware. However, if you're viewing this repo and are interested in dipping
your toes into the computer vision realm, the `state` and `score` modules are good pieces of code to digest. They 
provide an actual real-world example of techniques you'll find all over the web, such as template matching and image hashing.

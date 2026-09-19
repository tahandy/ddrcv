# FFmpeg Recorder

Double-click `apps\scripts\ffmpeg_record_gui.bat`. It uses the checkout's Windows
Python environment, or the Windows `pyw` launcher if there is no local environment.
You can also run `python apps\scripts\ffmpeg_record_gui.py` from the repository root.
The existing `ffmpeg_record.bat` is unchanged.

This standalone utility uses only Python's standard library, including Tkinter,
and your existing FFmpeg executable. No pip packages, preview, web server, or DDRCV
recognition runtime are required. Standard Windows Python includes Tkinter.
The dark colors, Segoe UI typography, panels, and blue Start button match the
DDRCV driver GUI using Tkinter's bundled theme engine.

1. Choose `ffmpeg.exe` if it was not found on PATH or at
   `C:\code\ffmpeg\bin\ffmpeg.exe`.
   If needed, click **Download FFmpeg** to open the
   [official download page](https://ffmpeg.org/download.html), choose a Windows
   build, extract it, and use **Browse…** to select its `bin\ffmpeg.exe`.
2. Click **Refresh**, select a camera, and optionally select an audio device.
   Audio defaults to **(No audio)** on first use.
3. Choose a recording folder. Resolution and frame rate default to **1280x720 / 30**;
   the camera must support the requested mode. Fractional rates such as
   `30000/1001` are accepted.
4. Click **Start recording**, then **Stop** to finish the file. Closing the window
   during capture also requests a clean stop and waits for FFmpeg to finish.

Each recording has a timestamped `.mkv` filename. Files are never overwritten.
Video uses H.264 (`libx264`, veryfast, CRF 18); optional audio uses AAC at 192 kb/s.
Your FFmpeg build must contain those encoders and DirectShow support. The timer
shows recorded media time reported by FFmpeg, not merely time since clicking Start.
Device discovery and pipe reads run in background threads.

Settings are saved in `%LOCALAPPDATA%\DDRcv\ffmpeg_record_gui.json`.
If FFmpeg cannot open the device, the window shows its diagnostic messages. Close
other applications using the capture device and confirm the selected mode is
supported. After ten seconds of waiting for Stop, **Force stop** becomes available;
it asks before terminating FFmpeg because the file may be incomplete.

Implementation references: [FFmpeg DirectShow devices](https://ffmpeg.org/ffmpeg-devices.html#dshow)
and [FFmpeg progress output](https://ffmpeg.org/ffmpeg.html#toc-Advanced-options).

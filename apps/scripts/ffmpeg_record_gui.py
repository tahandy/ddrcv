"""Standalone Windows FFmpeg recorder. Uses only Python's standard library."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser


NO_AUDIO = "(No audio)"
CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FFMPEG_DOWNLOAD_URL = "https://ffmpeg.org/download.html"
# Match ddrcv/desktop/static/desk.css without loading the driver or a web runtime.
COLORS = {
    "bg": "#202020", "surface": "#2b2b2b", "field": "#333333",
    "border": "#484848", "text": "#f0f0f0", "muted": "#bdbdbd",
    "accent": "#579ff2", "danger": "#ffb4ab",
}


def style_window(root):
    """Use Tk's bundled theme engine so Windows native widgets honor dark colors."""
    c = COLORS
    root.configure(background=c["bg"])
    root.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")
    root.option_add("*TCombobox*Listbox.background", c["field"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#101d2b")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=c["surface"], foreground=c["text"],
                    font=("Segoe UI", 10), bordercolor=c["border"],
                    lightcolor=c["border"], darkcolor=c["border"], focuscolor=c["accent"])
    style.configure("App.TFrame", background=c["bg"])
    style.configure("Panel.TFrame", borderwidth=1, relief="solid")
    style.configure("Title.TLabel", background=c["bg"], font=("Segoe UI", 13, "bold"))
    style.configure("Subtitle.TLabel", background=c["bg"], foreground=c["muted"])
    style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"))
    style.configure("Muted.TLabel", foreground=c["muted"], font=("Segoe UI", 9))
    style.configure("Timer.TLabel", font=("Consolas", 22), foreground=c["accent"])
    style.configure("TButton", background="#353535", bordercolor="#595959", padding=(12, 5))
    style.map("TButton", background=[("disabled", "#292929"), ("pressed", "#292929"), ("active", "#414141")],
              foreground=[("disabled", "#a6a6a6")],
              bordercolor=[("disabled", "#444444"), ("focus", c["accent"]), ("active", "#777777")])
    style.configure("Primary.TButton", background=c["accent"], foreground="#101d2b", bordercolor=c["accent"])
    style.map("Primary.TButton", background=[("disabled", "#292929"), ("pressed", "#4389db"), ("active", "#7bb4f6")],
              foreground=[("disabled", "#a6a6a6"), ("!disabled", "#101d2b")])
    style.configure("Danger.TButton", foreground=c["danger"])
    style.configure("Link.TButton", background=c["surface"], foreground=c["accent"],
                    borderwidth=0, padding=(0, 3), font=("Segoe UI", 9, "underline"))
    style.map("Link.TButton", background=[("active", c["surface"]), ("pressed", c["surface"])],
              foreground=[("active", "#7bb4f6")])
    for name in ("TEntry", "TCombobox"):
        style.configure(name, fieldbackground=c["field"], foreground=c["text"],
                        insertcolor=c["text"], bordercolor="#575757", padding=5,
                        selectbackground=c["accent"], selectforeground="#101d2b",
                        arrowcolor=c["text"])
        style.map(name, fieldbackground=[("disabled", "#292929"), ("readonly", c["field"])],
                  foreground=[("disabled", "#a6a6a6"), ("readonly", c["text"])],
                  bordercolor=[("focus", c["accent"])],
                  selectbackground=[("!disabled", c["accent"])],
                  selectforeground=[("!disabled", "#101d2b")])
    style.configure("Vertical.TScrollbar", troughcolor=c["bg"], background=c["field"],
                    arrowcolor=c["muted"], borderwidth=0)
    style.map("Vertical.TScrollbar", background=[("disabled", c["field"]), ("pressed", c["accent"]), ("active", "#414141")],
              arrowcolor=[("disabled", c["muted"]), ("active", c["text"])])


@dataclass(frozen=True)
class Device:
    name: str
    number: int = 0

    @property
    def label(self):
        return self.name if not self.number else f"{self.name} [#{self.number + 1}]"


def parse_devices(text):
    """Read modern and older DirectShow listings; ignore alternative-name lines."""
    devices = {"video": [], "audio": []}
    section = None
    for line in text.splitlines():
        if "DirectShow video devices" in line:
            section = "video"
        elif "DirectShow audio devices" in line:
            section = "audio"
        if "Alternative name" in line:
            continue
        match = re.search(r'\]\s+"(.*)"\s*(?:\((video|audio)\))?\s*$', line)
        if match and (kind := match[2] or section) in devices:
            name = match[1]
            number = sum(d.name == name for d in devices[kind])
            devices[kind].append(Device(name, number))
    return devices


def resolve_ffmpeg(value):
    value = value.strip().strip('"')
    found = shutil.which(value) if value else None
    if found:
        return found
    if value and Path(value).is_file():
        return str(Path(value).resolve())
    raise ValueError("Choose ffmpeg.exe, or put FFmpeg on PATH.")


def list_devices(executable):
    result = subprocess.run(
        [executable, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
        errors="replace", timeout=20, creationflags=CREATE_FLAGS,
    )
    # DirectShow intentionally exits nonzero after listing devices.
    devices = parse_devices(result.stderr)
    if not devices["video"]:
        raise ValueError("No video capture devices found.\n\n" + result.stderr[-2500:])
    return devices


def recording_command(executable, video, audio, size, fps, output):
    if not re.fullmatch(r"[1-9]\d{1,4}x[1-9]\d{1,4}", size):
        raise ValueError("Resolution must look like 1280x720.")
    try:
        rate = Fraction(fps)
        if not 0 < rate <= 240:
            raise ValueError
    except (ValueError, ZeroDivisionError):
        raise ValueError("Frame rate must be between 0 and 240 (for example 30 or 30000/1001).") from None
    source = f"video={video.name}"
    command = [
        executable, "-hide_banner", "-n", "-nostats", "-progress", "pipe:1",
        "-f", "dshow", "-rtbufsize", "256M", "-framerate", fps, "-video_size", size,
        "-video_device_number", str(video.number),
    ]
    if audio:
        source += f":audio={audio.name}"
        command += ["-audio_device_number", str(audio.number)]
    # Pass arguments directly: shell quoting must not become part of a device name.
    command += ["-i", source, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    command += ["-c:a", "aac", "-b:a", "192k"] if audio else ["-an"]
    return command + [str(output)]


class Recording:
    """Drain both pipes off the UI thread with bounded diagnostic storage."""

    def __init__(self, command):
        self.lock = threading.Lock()
        self.lines = deque(maxlen=80)
        self.frames = 0
        self.media_time = "00:00:00"
        self.returncode = None
        self.done = threading.Event()
        self.started = time.monotonic()
        self.stop_at = None
        self.forced = False
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", bufsize=1, creationflags=CREATE_FLAGS,
        )
        threading.Thread(target=self._monitor, daemon=True).start()

    def _read_errors(self):
        with self.process.stderr as stream:
            for line in stream:
                with self.lock:
                    self.lines.append(line.rstrip())

    def _monitor(self):
        reader = threading.Thread(target=self._read_errors, daemon=True)
        reader.start()
        with self.process.stdout as stream:
            for line in stream:
                key, _, value = line.strip().partition("=")
                with self.lock:
                    if key == "frame" and value.isdigit():
                        self.frames = int(value)
                    elif key == "out_time":
                        self.media_time = value.split(".")[0]
        self.returncode = self.process.wait()
        reader.join()
        self.process.stdin.close()
        self.done.set()

    def snapshot(self):
        with self.lock:
            return self.frames, self.media_time, "\n".join(self.lines)

    def stop(self):
        if self.stop_at is not None or self.done.is_set():
            return
        self.stop_at = time.monotonic()
        try:
            self.process.stdin.write("q\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            pass  # Exit may race with Stop; the monitor reports the outcome.

    def force_stop(self):
        if self.process.poll() is None:
            self.forced = True
            self.process.kill()


def settings_path():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DDRcv" / "ffmpeg_record_gui.json"


class RecorderGUI:
    def __init__(self, root, config_path=None, auto_scan=True):
        self.root = root
        self.config_path = config_path or settings_path()
        self.recording = None
        self.output = None
        self.closing = False
        self.scanning = False
        self.events = queue.Queue()
        self.devices = {"video": [], "audio": []}
        self.editors = []
        defaults = {
            "ffmpeg": shutil.which("ffmpeg") or r"C:\code\ffmpeg\bin\ffmpeg.exe",
            "video": "USB Video", "audio": NO_AUDIO,
            "folder": str(Path.home() / "Videos"), "size": "1280x720", "fps": "30",
        }
        load_warning = ""
        try:
            saved = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("Expected a settings object")
            defaults.update({k: v for k, v in saved.items() if k in defaults and isinstance(v, str)})
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            load_warning = "Saved settings could not be read; using defaults."
        self.values = {key: tk.StringVar(root, value) for key, value in defaults.items()}
        self.status = tk.StringVar(root, load_warning or "Ready. Refresh devices to select a camera.")
        self.elapsed = tk.StringVar(root, "00:00:00")
        self.file_label = tk.StringVar(root, "A timestamped .mkv file will be created for each recording.")
        root.title("DDRCV • FFmpeg Recorder")
        root.minsize(720, 660)
        style_window(root)
        outer = ttk.Frame(root, padding=16, style="App.TFrame")
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="DDRCV", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="FFmpeg Recorder", style="Subtitle.TLabel").pack(side="left", padx=14)
        frame = ttk.Frame(outer, padding=(14, 12), style="Panel.TFrame")
        frame.pack(fill="x", pady=(0, 12))
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Capture configuration", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        for row, key, label in [
            (1, "ffmpeg", "FFmpeg"), (3, "video", "Camera"), (4, "audio", "Audio"),
            (5, "folder", "Save to"), (6, "size", "Resolution"), (7, "fps", "Frame rate"),
        ]:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            if key in ("video", "audio", "size", "fps"):
                widget = ttk.Combobox(frame, textvariable=self.values[key])
                if key in ("video", "audio"):
                    widget.configure(state="readonly")
                else:
                    widget.configure(values=("1280x720", "1920x1080", "640x480") if key == "size" else ("30", "60", "30000/1001", "60000/1001"))
            else:
                widget = ttk.Entry(frame, textvariable=self.values[key])
            widget.grid(row=row, column=1, sticky="ew", pady=5)
            self.editors.append((widget, str(widget.cget("state"))))
            if key == "video":
                self.video_box = widget
            elif key == "audio":
                self.audio_box = widget
            if key in ("ffmpeg", "folder", "video"):
                action = self.refresh if key == "video" else lambda k=key: self.browse(k)
                button = ttk.Button(frame, text="Refresh" if key == "video" else "Browse…", command=action)
                button.grid(row=row, column=2, padx=(8, 0))
                self.editors.append((button, "normal"))
        download_row = ttk.Frame(frame)
        download_row.grid(row=2, column=1, columnspan=2, sticky="w", pady=(0, 5))
        self.download_button = ttk.Button(download_row, text="Download FFmpeg", style="Link.TButton",
                                          cursor="hand2", command=self.download_ffmpeg)
        self.download_button.pack(side="left")
        ttk.Label(download_row, text="Windows builds · extract, then Browse to ffmpeg.exe",
                  style="Muted.TLabel").pack(side="left", padx=(10, 0))
        session = ttk.Frame(outer, padding=(14, 12), style="Panel.TFrame")
        session.pack(fill="x", pady=(0, 12))
        ttk.Label(session, text="Recording", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        controls = ttk.Frame(session)
        controls.pack(fill="x", pady=(0, 10))
        self.start_button = ttk.Button(controls, text="Start recording", command=self.start, style="Primary.TButton")
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        self.force_button = ttk.Button(controls, text="Force stop", command=self.force_stop, state="disabled", style="Danger.TButton")
        self.force_button.pack(side="left")
        ttk.Label(controls, textvariable=self.elapsed, style="Timer.TLabel").pack(side="right")
        status_label = ttk.Label(session, textvariable=self.status, wraplength=620)
        status_label.pack(anchor="w", pady=(0, 5))
        file_label = ttk.Label(session, textvariable=self.file_label, wraplength=620, style="Muted.TLabel")
        file_label.pack(anchor="w")
        session.bind("<Configure>", lambda event: [label.configure(wraplength=max(200, event.width - 30))
                                                  for label in (status_label, file_label)])
        diagnostics = ttk.Frame(outer, padding=(14, 12), style="Panel.TFrame")
        diagnostics.pack(fill="both", expand=True)
        ttk.Label(diagnostics, text="FFmpeg messages", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        log_frame = ttk.Frame(diagnostics)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=5, wrap="word", state="disabled", font=("Consolas", 9),
                           background=COLORS["bg"], foreground=COLORS["muted"],
                           insertbackground=COLORS["text"], selectbackground=COLORS["accent"],
                           selectforeground="#101d2b", relief="flat", borderwidth=0,
                           highlightthickness=1, highlightbackground=COLORS["border"],
                           highlightcolor=COLORS["accent"], padx=8, pady=8)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.last_log = None
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Destroy>", self._destroyed, add="+")
        self.timer = root.after(200, self.tick)
        self.scan_timer = None
        if auto_scan:
            self.scan_timer = root.after(100, self.refresh)

    def _destroyed(self, event):
        if event.widget is self.root:
            for timer in (self.timer, self.scan_timer):
                if timer:
                    self.root.after_cancel(timer)

    def set_busy(self, busy):
        for widget, normal in self.editors:
            widget.configure(state="disabled" if busy else normal)
        self.start_button.configure(state="disabled" if busy else "normal")

    def browse(self, key):
        if key == "ffmpeg":
            path = filedialog.askopenfilename(parent=self.root, title="Choose FFmpeg", filetypes=[("FFmpeg", "*.exe")])
        else:
            path = filedialog.askdirectory(parent=self.root, title="Recording folder", initialdir=self.values[key].get())
        if path:
            self.values[key].set(path)
            if key == "ffmpeg":
                self.refresh()

    def download_ffmpeg(self):
        try:
            if not webbrowser.open(FFMPEG_DOWNLOAD_URL, new=2):
                raise OSError("No browser could be opened.")
        except (OSError, webbrowser.Error) as error:
            messagebox.showerror("Download FFmpeg", f"{error}\n\nVisit {FFMPEG_DOWNLOAD_URL}", parent=self.root)

    def refresh(self):
        if self.recording or self.scanning:
            return
        try:
            executable = resolve_ffmpeg(self.values["ffmpeg"].get())
        except ValueError as error:
            self.status.set("FFmpeg not found. Use Download FFmpeg, then Browse to ffmpeg.exe.")
            self.update_log(str(error))
            return
        self.scanning = True
        self.set_busy(True)
        self.status.set("Looking for capture devices…")

        def scan():
            try:
                self.events.put(("devices", list_devices(executable)))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                self.events.put(("error", str(error)))

        threading.Thread(target=scan, daemon=True).start()

    def save(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        # Separate temporary paths also permit multiple recorder windows.
        temporary = self.config_path.with_suffix(f".{os.getpid()}.{id(self)}.tmp")
        temporary.write_text(json.dumps({k: v.get() for k, v in self.values.items()}, indent=2), encoding="utf-8")
        temporary.replace(self.config_path)

    def start(self):
        if self.recording or self.scanning:
            return
        try:
            executable = resolve_ffmpeg(self.values["ffmpeg"].get())
            video = next((d for d in self.devices["video"] if d.label == self.values["video"].get()), None)
            if video is None:
                raise ValueError("Refresh devices and select a camera first.")
            audio = None
            if self.values["audio"].get() != NO_AUDIO:
                audio = next((d for d in self.devices["audio"] if d.label == self.values["audio"].get()), None)
                if audio is None:
                    raise ValueError("Select an audio device or choose (No audio).")
            folder_text = self.values["folder"].get().strip()
            if not folder_text:
                raise ValueError("Choose a recording folder.")
            folder = Path(folder_text).expanduser().resolve()
            output = folder / (datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f") + ".mkv")
            command = recording_command(executable, video, audio, self.values["size"].get().strip(), self.values["fps"].get().strip(), output)
            folder.mkdir(parents=True, exist_ok=True)
            self.save()
            self.recording = Recording(command)
            self.output = output
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not start recording", str(error), parent=self.root)
            return
        self.set_busy(True)
        self.stop_button.configure(state="normal")
        self.elapsed.set("00:00:00")
        self.file_label.set(str(self.output))
        self.status.set("Starting capture…")
        self.update_log("")

    def stop(self):
        if self.recording:
            self.recording.stop()
            self.stop_button.configure(state="disabled")
            self.status.set("Stopping — finishing the recording file…")

    def force_stop(self):
        if self.recording and messagebox.askyesno(
            "Force stop?", "FFmpeg has not stopped. Force it to exit? The recording may be incomplete.", parent=self.root,
        ):
            self.recording.force_stop()
            self.force_button.configure(state="disabled")

    def update_log(self, text):
        if text != self.last_log:
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.insert("end", text)
            self.log.see("end")
            self.log.configure(state="disabled")
            self.last_log = text

    def tick(self):
        try:
            kind, payload = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.scanning = False
            self.set_busy(False)
            if kind == "devices":
                self.devices = payload
                for kind, box in (("video", self.video_box), ("audio", self.audio_box)):
                    labels = [d.label for d in payload[kind]]
                    if kind == "audio":
                        labels.insert(0, NO_AUDIO)
                    box.configure(values=labels)
                    if self.values[kind].get() not in labels:
                        self.values[kind].set(labels[0])
                self.status.set("Ready.")
            else:
                self.devices = {"video": [], "audio": []}
                self.status.set("Device refresh failed. Check FFmpeg and reconnect the camera.")
                self.update_log(payload)
        recording = self.recording
        if recording:
            frames, media_time, log = recording.snapshot()
            self.update_log(log)
            self.elapsed.set(media_time)
            if recording.stop_at is not None:
                if time.monotonic() - recording.stop_at > 10 and not recording.done.is_set():
                    self.status.set("FFmpeg is still stopping. You can wait or force stop.")
                    self.force_button.configure(state="normal")
            elif frames:
                self.status.set(f"Recording • {frames:,} frames")
            elif time.monotonic() - recording.started > 10:
                self.status.set("Still waiting for video. Check the camera or click Stop.")
            if recording.done.is_set():
                self.recording = None
                self.set_busy(False)
                self.stop_button.configure(state="disabled")
                self.force_button.configure(state="disabled")
                try:
                    has_file = self.output.is_file() and self.output.stat().st_size > 0
                except OSError:
                    has_file = False
                if recording.returncode == 0 and frames > 0 and has_file and not recording.forced:
                    self.status.set("Recording saved.")
                else:
                    self.closing = False
                    self.status.set("Recording did not finish successfully. See FFmpeg messages below.")
                    messagebox.showerror("Recording failed", "The recording may be missing or incomplete.\n\n" + log[-2000:], parent=self.root)
                if self.closing:
                    self.root.destroy()
                    return
        self.timer = self.root.after(200, self.tick)

    def close(self):
        if self.recording:
            self.closing = True
            self.stop()
        else:
            try:
                self.save()
            except OSError as error:
                messagebox.showwarning("Settings", f"Could not save settings:\n{error}", parent=self.root)
            self.root.destroy()


def main():
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    if os.name != "nt":
        root.withdraw()
        messagebox.showerror("FFmpeg Recorder", "This recorder uses Windows DirectShow capture devices.", parent=root)
        root.destroy()
        return
    RecorderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

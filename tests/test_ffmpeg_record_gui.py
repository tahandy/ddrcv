"""Focused standard-library tests; Windows acceptance uses synthetic AV, no camera."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "apps" / "scripts" / "ffmpeg_record_gui.py"
spec = importlib.util.spec_from_file_location("ffmpeg_record_gui", SOURCE)
gui = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gui
spec.loader.exec_module(gui)


class RecorderTests(unittest.TestCase):
    def test_device_listing_with_duplicates_unicode_and_aliases(self):
        result = gui.parse_devices('\n'.join([
            '[dshow @ abc] "USB Video" (video)',
            '[dshow @ abc] Alternative name "@device_123"',
            '[dshow @ abc] "USB Video" (video)',
            '[dshow @ abc] "Mikrofon – 音声" (audio)',
        ]))
        self.assertEqual(result["video"], [gui.Device("USB Video"), gui.Device("USB Video", 1)])
        self.assertEqual(result["audio"], [gui.Device("Mikrofon – 音声")])
        self.assertEqual(result["video"][1].label, "USB Video [#2]")

    def test_older_device_listing(self):
        result = gui.parse_devices('\n'.join([
            '[dshow @ abc] DirectShow video devices (some may be both video and audio devices)',
            '[dshow @ abc] "Camera"',
            '[dshow @ abc] DirectShow audio devices',
            '[dshow @ abc] "Audio"',
        ]))
        self.assertEqual(result, {"video": [gui.Device("Camera")], "audio": [gui.Device("Audio")]})

    def test_command_preserves_names_and_refuses_overwrite(self):
        command = gui.recording_command("ffmpeg", gui.Device("USB Video", 1), gui.Device("USB Audio"), "1280x720", "30000/1001", "a folder/out.mkv")
        self.assertIn("-n", command)
        self.assertNotIn("-y", command)
        self.assertEqual(command[command.index("-i") + 1], "video=USB Video:audio=USB Audio")
        self.assertEqual(command[command.index("-video_device_number") + 1], "1")
        self.assertEqual(command[-1], "a folder/out.mkv")

    def test_bad_capture_modes_rejected(self):
        for size, fps in [("foo", "30"), ("1280x720", "0"), ("1280x720", "1/0"), ("1280x720", "nan"), ("1280x720", "241")]:
            with self.subTest(size=size, fps=fps), self.assertRaises(ValueError):
                gui.recording_command("ffmpeg", gui.Device("Camera"), None, size, fps, "out.mkv")

    def test_failed_child_drains_logs_and_finishes(self):
        code = "import sys; [print('diagnostic '+str(i), file=sys.stderr) for i in range(5000)]; sys.exit(7)"
        recording = gui.Recording([sys.executable, "-c", code])
        self.assertTrue(recording.done.wait(10))
        self.assertEqual(recording.returncode, 7)
        self.assertEqual(len(recording.snapshot()[2].splitlines()), 80)
        recording.stop()  # Safe after an early exit.


FFMPEG = Path(r"C:\code\ffmpeg\bin\ffmpeg.exe")
FFPROBE = FFMPEG.with_name("ffprobe.exe")


@unittest.skipUnless(os.name == "nt" and FFMPEG.exists() and FFPROBE.exists(), "Needs Windows Tk and local FFmpeg/FFprobe")
class WindowsAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ffmpeg-recorder-test-")
        self.root = gui.tk.Tk()
        self.root.withdraw()
        self.app = gui.RecorderGUI(self.root, Path(self.temp.name) / "settings.json", auto_scan=False)
        self.app.devices = {"video": [gui.Device("Synthetic")], "audio": []}
        self.app.values["video"].set("Synthetic")
        self.app.values["ffmpeg"].set(str(FFMPEG))
        self.app.values["folder"].set(self.temp.name)
        self.error_patch = patch.object(gui.messagebox, "showerror")
        self.errors = self.error_patch.start()

    def tearDown(self):
        if self.app.recording:
            self.app.recording.force_stop()
            self.app.recording.done.wait(10)
        try:
            self.root.destroy()
        except gui.tk.TclError:
            pass
        self.error_patch.stop()
        self.temp.cleanup()

    def pump_until(self, condition, timeout=15):
        end = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > end:
                self.fail(f"GUI timed out: {self.app.status.get()} / {self.app.last_log}")
            self.root.update()
            time.sleep(.025)

    @staticmethod
    def synthetic_command(executable, video, audio, size, fps, output):
        return [executable, "-hide_banner", "-n", "-nostats", "-progress", "pipe:1",
                "-re", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
                "-re", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k", str(output)]

    def inspect_output(self, output):
        result = subprocess.run([str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual({s["codec_name"] for s in data["streams"]}, {"h264", "aac"})
        self.assertGreater(float(data["format"]["duration"]), 0)

    def test_real_record_stop_restart_and_close(self):
        with patch.object(gui, "recording_command", side_effect=self.synthetic_command):
            self.app.start()
            first = self.app.output
            self.assertEqual(str(self.app.start_button["state"]), "disabled")
            self.pump_until(lambda: self.app.recording.snapshot()[0] >= 15)
            self.app.stop()
            self.pump_until(lambda: self.app.recording is None)
            self.assertEqual(self.app.status.get(), "Recording saved.")
            self.inspect_output(first)
            self.app.start()
            second = self.app.output
            self.assertNotEqual(first, second)
            self.pump_until(lambda: self.app.recording.snapshot()[0] >= 15)
            self.app.close()
            self.pump_until(lambda: self.app.recording is None)
            self.inspect_output(second)
        self.errors.assert_not_called()
        saved = json.loads((Path(self.temp.name) / "settings.json").read_text())
        self.assertEqual(saved["video"], "Synthetic")

    def test_failed_capture_restores_controls(self):
        with patch.object(gui, "recording_command", return_value=[str(FFMPEG), "-i", "nonexistent-recorder-input"]):
            self.app.start()
        self.pump_until(lambda: self.app.recording is None)
        self.errors.assert_called_once()
        self.assertEqual(str(self.app.start_button["state"]), "normal")
        self.assertIn("did not finish successfully", self.app.status.get())

    def test_force_stop_requires_confirmation(self):
        with patch.object(gui, "recording_command", side_effect=self.synthetic_command):
            self.app.start()
        self.pump_until(lambda: self.app.recording.snapshot()[0] >= 15)
        with patch.object(gui.messagebox, "askyesno", return_value=False):
            self.app.force_stop()
        self.assertFalse(self.app.recording.forced)
        with patch.object(gui.messagebox, "askyesno", return_value=True):
            self.app.force_stop()
        self.pump_until(lambda: self.app.recording is None)
        self.errors.assert_called_once()
        self.assertIn("did not finish successfully", self.app.status.get())


if __name__ == "__main__":
    unittest.main()

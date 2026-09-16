"""Sequential local playback. Media time is independent of playback wall time."""
from dataclasses import dataclass
from pathlib import Path
import math
import time

import cv2


@dataclass
class FramePacket:
    image: object
    timestamp: float
    index: int


def normalize_frame(frame, resize_to_720p=False):
    height, width = frame.shape[:2]
    if (height, width) == (720, 1280):
        return frame
    if width * 9 != height * 16:
        raise ValueError(f'{width}x{height} is not a full 16:9 game frame. Prepare an uncropped game recording without borders or overlays.')
    if not resize_to_720p:
        raise ValueError(f'Expected 1280x720 capture; received {width}x{height}. Enable resize to 720p for this full-frame recording.')
    return cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA if height > 720 else cv2.INTER_LINEAR)


class FileSource:
    def __init__(self, path, kind='video', resize_to_720p=False):
        self.path = str(Path(path).expanduser().resolve())
        self.kind = kind
        self.resize_to_720p = resize_to_720p
        self.capture = None
        self.ended = False
        self.index = 0
        self.source_time = 0.0
        self._last_timestamp = None
        self._deadline = None
        if not Path(self.path).is_file():
            raise ValueError(f'File does not exist: {self.path}')
        try:
            if kind == 'image':
                self.image = cv2.imread(self.path)
                if self.image is None:
                    raise ValueError('Image cannot be decoded. Use PNG or JPEG.')
                self.height, self.width = self.image.shape[:2]
                self.fps, self.count = 0.0, 1
                normalize_frame(self.image, resize_to_720p)
            elif kind == 'video':
                self.capture = cv2.VideoCapture(self.path)
                if not self.capture.isOpened():
                    raise ValueError('Video cannot be decoded. Try an MP4/H.264 recording.')
                self.fps = float(self.capture.get(cv2.CAP_PROP_FPS))
                self.count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
                self.width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if not math.isfinite(self.fps) or self.fps <= 0 or self.count <= 0:
                    raise ValueError('Video has no usable frame rate or frame count. Remux it to a normal seekable MP4.')
                ok, frame = self.capture.read()
                if not ok:
                    raise ValueError('Video contains no readable frames.')
                normalize_frame(frame, resize_to_720p)
                self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            else:
                raise ValueError('File source must be video or image')
        except Exception:
            self.stop()
            raise

    @property
    def metadata(self):
        return dict(kind=self.kind, path=self.path, width=self.width, height=self.height,
                    fps=self.fps, frames=self.count, duration=self.count / self.fps if self.fps else 0,
                    resized=(self.width, self.height) != (1280, 720))

    def start(self):
        self._deadline = None

    def read(self):
        if self.ended:
            return None
        if self.kind == 'image':
            if self.index:
                self.ended = True
                return None
            frame, timestamp = self.image.copy(), 0.0
        else:
            ok, frame = self.capture.read()
            if not ok:
                self.ended = True
                return None
            timestamp = self.capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if not math.isfinite(timestamp) or timestamp < 0 or (self.index > 0 and timestamp == 0) or (self._last_timestamp is not None and timestamp <= self._last_timestamp):
                timestamp = max(self.index / self.fps, self._last_timestamp + 1 / self.fps if self._last_timestamp is not None else 0)
        packet = FramePacket(normalize_frame(frame, self.resize_to_720p), timestamp, self.index)
        self.source_time = timestamp
        self._last_timestamp = timestamp
        self.index += 1
        return packet

    def get_frame(self):
        # Compatibility adapter for the CLI; the workbench controls pacing itself.
        if self._deadline is not None:
            time.sleep(max(0, self._deadline - time.monotonic()))
        packet = self.read()
        if packet is None:
            return None
        self._deadline = time.monotonic() + (1 / self.fps if self.fps else 0)
        return packet.image

    def seek(self, seconds):
        if self.kind != 'video' or not math.isfinite(seconds):
            raise ValueError('Seek requires a video and a finite time')
        target = min(self.count - 1, max(0, int(seconds * self.fps)))
        if not self.capture.set(cv2.CAP_PROP_POS_FRAMES, target):
            raise ValueError('This video decoder cannot seek; try remuxing to MP4')
        self.index, self.ended = target, False
        self._last_timestamp = self._deadline = None

    def stop(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None

from pathlib import Path
from datetime import datetime
from PIL import Image


class Screenshot:
    def __init__(self, screenshot_dir, timestamp_fmt='%Y%m%d_%H%M'):
        self.screenshot_dir = Path(screenshot_dir)
        self.timestamp_fmt = timestamp_fmt

    def _get_timestamp(self):
        return datetime.now().strftime(self.timestamp_fmt)

    def save(self, rgb_image, suffix=None):
        if not self.screenshot_dir.exists():
            self.screenshot_dir.mkdir(exist_ok=True, parents=True)

        if suffix is None:
            suffix = ''
        else:
            suffix = '_' + suffix

        timestamp = self._get_timestamp()
        print('timestamp: ', timestamp)
        png_file = Path(self.screenshot_dir) / f'{timestamp}{suffix}.png'
        print('png_file: ', png_file)
        im = Image.fromarray(rgb_image)
        im.save(png_file)
        return png_file

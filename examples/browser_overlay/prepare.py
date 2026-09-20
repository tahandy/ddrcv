"""Optional example utility: copy the browser source with a custom feed URL."""
import argparse
from html import escape
from pathlib import Path


DEFAULT_FEED = 'ws://127.0.0.1:9000'


def prepare_overlay(directory, feed_url=DEFAULT_FEED):
    """Write only our three assets; the HTML path remains stable across restarts."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    assets = Path(__file__).resolve().parent
    for name in ('overlay.css', 'overlay.js', 'index.html'):
        content = assets.joinpath(name).read_text(encoding='utf-8')
        if name == 'index.html':
            content = content.replace(f'data-feed="{DEFAULT_FEED}"',
                                      f'data-feed="{escape(feed_url, quote=True)}"')
        (directory / name).write_text(content, encoding='utf-8')
    return directory / 'index.html'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Output folder for the three browser-source files')
    parser.add_argument('--feed', default=DEFAULT_FEED, help='WebSocket URL (default: %(default)s)')
    args = parser.parse_args()
    print(prepare_overlay(args.directory, args.feed))


if __name__ == '__main__':
    main()

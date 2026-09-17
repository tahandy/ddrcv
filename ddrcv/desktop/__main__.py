import argparse
import json
import os
from pathlib import Path
import sys


def checks():
    import importlib.util
    result = []
    for module in ('webview', 'pystray', 'cv2', 'numpy', 'flask', 'websockets', 'obsws_python', 'pygame'):
        result.append(dict(name=module, ok=importlib.util.find_spec(module) is not None))
    edge = False
    detail = 'Windows and Microsoft Edge WebView2 Runtime are required'
    if sys.platform == 'win32' and importlib.util.find_spec('webview'):
        try:
            from webview.platforms.winforms import _is_chromium
            edge = bool(_is_chromium())
            detail = 'Microsoft Edge WebView2 Runtime'
        except Exception as error:
            detail = str(error)
    result.append(dict(name='WebView2', ok=edge, detail=detail))
    from ddrcv.apps.driver_config import normalize_config
    from ddrcv.state.tbd5_states import StateRotation
    from ddrcv.score.score_extractor import ScoreExtractor
    try:
        StateRotation(**normalize_config({})['state'])
        ScoreExtractor(None)
        result.append(dict(name='Recognition templates', ok=True))
    except Exception as error:
        result.append(dict(name='Recognition templates', ok=False, detail=str(error)))
    return result


def main():
    parser = argparse.ArgumentParser(description='DDRCV Tournament desktop')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'DDRCV' / 'tournament')
    parser.add_argument('--no-panel', action='store_true', help='Start the tray without opening its window')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        result = checks()
        print(json.dumps(result, indent=2))
        return 0 if all(r['ok'] for r in result) else 1
    from ddrcv.desktop.host import run
    try:
        run(args.data_dir.resolve(), args.config, args.no_panel)
    except Exception as error:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'DDRCV could not start', 0x10)
        else:
            print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

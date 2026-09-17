"""Disposable WebView2 process. Closing this window never owns the driver."""
import json
import sys
import threading
import urllib.request


def main():
    context = json.loads(sys.stdin.readline())
    import webview
    window = None
    closing = threading.Event()

    def request(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(context['url'] + path, data=data,
               headers={'X-Desk-Token': context['token'], 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    class Bridge:
        def session(self):
            return dict(token=context['token'])

        def pick(self, action, path=''):
            if action == 'directory':
                result = window.create_file_dialog(webview.FileDialog.FOLDER)
            elif action == 'save':
                result = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=path or 'tournament.json',
                    file_types=('JSON configurations (*.json)', 'All files (*.*)'))
            else:
                result = window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                    file_types=('JSON configurations (*.json)', 'All files (*.*)') if action == 'config' else ('Media files (*.mp4;*.mkv;*.avi;*.png;*.jpg)', 'All files (*.*)'))
            if not result:
                return None
            return result if isinstance(result, str) else result[0]

        def close_ready(self):
            closing.set()
            window.destroy()

    try:
        prefs = request('/api/config')['preferences']
    except Exception:
        prefs = context.get('preferences', {})
    window = webview.create_window('DDRCV Tournament', context['url'], js_api=Bridge(),
                width=prefs.get('width', 1120), height=prefs.get('height', 800), min_size=(760, 560))

    def visibility(visible):
        try:
            window.run_js('window.deskVisibility && window.deskVisibility(' + ('true' if visible else 'false') + ')')
        except Exception:
            pass

    def on_closing():
        if closing.is_set():
            return True
        def flush():
            try:
                window.run_js('window.deskClose ? window.deskClose() : window.pywebview.api.close_ready()')
            except Exception:
                closing.set()
                window.destroy()
        threading.Thread(target=flush, daemon=True).start()
        return False

    def save_size(width, height):
        # Window geometry is independent of tournament configs.
        context['preferences'] = dict(width=width, height=height)

    window.events.closing += on_closing
    window.events.minimized += lambda: visibility(False)
    window.events.restored += lambda: visibility(True)
    window.events.resized += save_size

    def listen():
        for line in sys.stdin:
            message = json.loads(line)
            if message['action'] == 'focus':
                window.restore()
                window.show()
                visibility(True)
            elif message['action'] == 'exit':
                closing.set()
                window.destroy()
                return
        closing.set()
        window.destroy()

    def ready():
        threading.Thread(target=listen, name='desk-window-control', daemon=True).start()

    webview.start(ready, gui='edgechromium', debug=False)
    try:
        request('/api/preferences', context.get('preferences', {}))
    except Exception:
        pass


if __name__ == '__main__':
    main()

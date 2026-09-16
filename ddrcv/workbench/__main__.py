import argparse
import logging
import threading
import webbrowser


def main():
    parser = argparse.ArgumentParser(description='DDRCV local rehearsal workbench')
    parser.add_argument('--port', type=int, default=5002)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir')
    parser.add_argument('--check', action='store_true', help='Print setup checks without launching a browser')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    # Polling and preview requests must not bury recognition/integration logs.
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    try:
        from werkzeug.serving import make_server
        from ddrcv.workbench.app import create_app
        from ddrcv.workbench.controller import Workbench
    except ImportError as error:
        parser.exit(1, f'Missing runtime dependency: {error}. Run setup_workbench.bat first.\n')
    wb = Workbench(args.data_dir, start_publisher=not args.check)
    server = None
    try:
        if args.check:
            import json
            print(json.dumps(wb.checks(), indent=2))
            return
        app = create_app(wb)
        try:
            server = make_server('127.0.0.1', args.port, app, threaded=True)
        except (OSError, SystemExit):
            parser.exit(1, f'Panel port {args.port} is occupied. Close the other panel or pass --port.\n')
        app.config['SHUTDOWN'] = server.shutdown
        url = f'http://localhost:{args.port}/'
        print(f'Rehearsal panel: {url}\nClean OBS browser source: {url}video\nPress Ctrl+C to stop.')
        if not args.no_browser:
            threading.Timer(.3, lambda: webbrowser.open(url)).start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        wb.close()
        if server:
            server.server_close()


if __name__ == '__main__':
    main()

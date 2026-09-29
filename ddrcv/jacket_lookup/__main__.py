"""Prepare an offline catalog, check readiness, or inspect a crop/splash."""
import argparse
import json
import os

for _variable in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[_variable] = '1'


def main():
    from .config import DEFAULTS
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('prepare', 'pack', 'check', 'lookup'):
        sub = commands.add_parser(command)
        sub.add_argument('--catalog-file', help='Portable .ddrcatalog input/output file')
        sub.add_argument('--assets-dir', help='Preparation cache or existing folder catalog (migration)')
        sub.add_argument('--mode', choices=('event', 'full'), default='event')
        sub.add_argument('--event', default=DEFAULTS['event'])
        sub.add_argument('--style', choices=('single', 'double'), default='single')
        sub.add_argument('--difficulty-method', choices=('template', 'ocr'), default='template')
        if command == 'prepare':
            sub.add_argument('--refresh', action='store_true')
            sub.add_argument('--ref', help='Explicit metadata commit/ref; otherwise latest is pinned once')
            sub.add_argument('--source-cache', help='Reuse an existing downloaded source cache')
        if command == 'lookup':
            sub.add_argument('--image', required=True)
            sub.add_argument('--splash', action='store_true')
            sub.add_argument('--names', action='store_true', help='Also read splash names once; no temporal confirmation')
    args = parser.parse_args()
    if args.command == 'lookup' and args.names and not args.splash:
        parser.error('--names requires --splash')
    from . import assets
    cfg = dict(mode=args.mode, event=args.event, style=args.style,
               difficulty_method=args.difficulty_method, assets_dir=args.assets_dir, catalog_file=args.catalog_file)
    if args.command == 'prepare':
        result = assets.prepare(cfg, refresh=args.refresh, ref=args.ref,
                                source_root=args.source_cache, progress=lambda m: print(m, flush=True))
    elif args.command == 'pack':
        result = assets.pack(cfg)
    elif args.command == 'check':
        result = assets.check(cfg)
    else:
        from .images import read_image
        frame = read_image(args.image)
        lookup = assets.load(cfg)
        if args.splash:
            processor = assets.processor(cfg, lookup=lookup)
            try:
                result = processor.analyze(frame, style=args.style)
            finally:
                processor.close()
            if args.names:
                from .names import PerPlayerNameReader
                from ddrcv.state.player_names import NAME_BOXES
                from .images import crop
                with PerPlayerNameReader() as reader:
                    result['player_names'] = reader.read({
                        int(p[1:])-1: crop(frame, NAME_BOXES[int(p[1:])-1])
                        for p in result.get('players', {})})
        else:
            result = lookup.lookup(frame)
            if result['accepted'] and lookup.entries[result['song']['index']]['sha256'] in lookup.selection['blocked_artwork']:
                result.update(accepted=False, song=None, reason='ambiguous_artwork')
    print(json.dumps(result, indent=2, ensure_ascii=True))
    if result.get('ok') is False:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

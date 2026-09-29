"""Pinned, cached DDRCardDraw adapter. No frontend scraping or runtime network."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import time
import unicodedata
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

REPOSITORY = 'noahm/DDRCardDraw'
DEFAULT_REF = 'c62053faa82df55ebc926812a7af684f520ae704'
DEFAULT_EVENT = 'dia_del_ritmo_26'
SCHEMA = 1


def dump_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    from uuid import uuid4
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_event(value):
    if '://' in value:
        url = urlparse(value)
        if url.scheme != 'https' or url.hostname not in ('ddr.tools', 'www.ddr.tools'):
            raise ValueError('Expected an https://ddr.tools/#game-<slug> URL or game slug')
        if not url.fragment.startswith('game-'):
            raise ValueError('The ddr.tools URL must contain #game-<slug>')
        value = url.fragment[5:]
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', value):
        raise ValueError('Invalid DDRCardDraw game slug')
    return value


def safe_jacket(path):
    p = PurePosixPath(path)
    if not path or p.is_absolute() or '..' in p.parts or '\\' in path or ':' in path:
        raise ValueError(f'Unsafe jacket path: {path!r}')
    return str(p)


def is_ddr_jacket(path):
    path = safe_jacket(path)
    return path.startswith('ddr_') or path.startswith('banner/ddr')


def effective_jacket(song, chart):
    path = chart.get('jacket') or song.get('jacket')
    return safe_jacket(path) if path else None


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def identity(song):
    if song.get('saHash'):
        return 'sa:' + song['saHash']
    key = normalize(song.get('name')) + '\0' + normalize(song.get('artist'))
    return 'meta:' + sha256(key.encode('utf-8'))[:24]


def same_song(left, right):
    # Never bridge a disagreement between two known stable identifiers.
    common = [field for field in ('saHash', 'saIndex') if left.get(field) and right.get(field)]
    if common:
        return all(left[field] == right[field] for field in common)
    return (normalize(left.get('name')), normalize(left.get('artist'))) == (
        normalize(right.get('name')), normalize(right.get('artist')))


def normalize_catalog(sources, event=None, commit=DEFAULT_REF):
    """Keep chart versions separate; fill only missing, unambiguous event scores."""
    world = sources.get('ddr_world', {}).get('songs', [])
    records = []
    for slug, data in sorted(sources.items()):
        if event and slug != event:
            continue
        for number, song in enumerate(data['songs']):
            jackets = {effective_jacket(song, c) for c in song['charts']}
            if not any(p and is_ddr_jacket(p) for p in jackets):
                continue
            matches = [s for s in world if same_song(song, s)]
            sid = identity(matches[0]) if len(matches) == 1 else identity(song)
            charts = []
            for chart in song['charts']:
                original_score = chart.get('maxScore')
                score, score_source = original_score, slug if original_score is not None else None
                if event and score is None and len(matches) == 1:
                    options = [c for c in matches[0]['charts'] if all(
                        c.get(k) == chart.get(k) for k in ('style', 'diffClass', 'lvl'))]
                    if len(options) == 1 and options[0].get('maxScore') is not None:
                        score, score_source = options[0]['maxScore'], 'ddr_world'
                charts.append(dict(style=chart['style'], difficulty=chart['diffClass'],
                                   level=chart['lvl'], max_ex=score,
                                   max_ex_source=score_source, original_max_ex=original_score,
                                   jacket=effective_jacket(song, chart), original=chart))
            records.append(dict(record_id=f'{slug}:{number}', song_id=sid, dataset=slug,
                                name=song['name'], artist=song['artist'], folder=song.get('folder'),
                                jacket=song.get('jacket'), charts=charts, original=song))
    return dict(schema=SCHEMA, repository=REPOSITORY, commit=commit,
                mode='event' if event else 'full', event=event, metadata_dataset=event or 'ddr_world',
                defaults=sources[event].get('defaults') if event else None, records=records)


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'ddrcv-jacket-poc'}), timeout=45) as response:
                return response.read()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(.5 * (attempt + 1))


def prepare(root, *, mode='event', event=DEFAULT_EVENT, ref=DEFAULT_REF, workers=8, include_world_artwork=False):
    """Download once, verify cached bytes on reruns, and preserve partial failures."""
    root = Path(root)
    event = parse_event(event)
    commit = ref if re.fullmatch('[0-9a-f]{40}', ref) else json.loads(fetch(
        f'https://api.github.com/repos/{REPOSITORY}/commits/{quote(ref, safe="")}'))['sha']
    cache = root / 'cache' / commit
    cache.mkdir(parents=True, exist_ok=True)
    checksums_path = cache / 'checksums.json'
    checksums = read_json(checksums_path) if checksums_path.exists() else {}

    def get(path):
        local = cache / path
        # A process may exit after publishing a download but before committing
        # checksums.json. Such a file is incomplete cache state: fetch it again.
        if local.exists() and path in checksums:
            data = local.read_bytes()
            if checksums.get(path) != sha256(data):
                raise ValueError(f'Cached source checksum mismatch: {local}')
        else:
            data = fetch(f'https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{quote(path, safe="/")}')
            local.parent.mkdir(parents=True, exist_ok=True)
            from uuid import uuid4
            temporary = local.with_name(local.name + '.' + uuid4().hex + '.tmp')
            try:
                temporary.write_bytes(data)
                temporary.replace(local)
            finally:
                temporary.unlink(missing_ok=True)
        checksums[path] = sha256(data)
        return data

    if mode == 'full':
        tree_file = cache / 'tree.json'
        if not tree_file.exists():
            tree = json.loads(fetch(f'https://api.github.com/repos/{REPOSITORY}/git/trees/{commit}?recursive=1'))
            if tree.get('truncated'):
                raise ValueError('Upstream tree is truncated; cannot claim a full catalog')
            dump_json(tree_file, tree)
        tree = read_json(tree_file)['tree']
        slugs = [PurePosixPath(e['path']).stem for e in tree
                 if e['path'].startswith('src/songs/') and e['path'].endswith('.json')]
    else:
        slugs = sorted({event, 'ddr_world'})
        tree = []
    sources = {}
    try:
        for slug in slugs:
            sources[slug] = json.loads(get(f'src/songs/{slug}.json'))
        catalog = normalize_catalog(sources, event if mode == 'event' else None, commit)
        if not catalog['records']:
            raise ValueError('No DDR records in the requested catalog')
        paths = {c['jacket'] for s in catalog['records'] for c in s['charts'] if c['jacket']}
        if include_world_artwork:
            # Alias detection must compare bytes even when a new WORLD song
            # references a newly named copy of an existing gallery jacket.
            paths.update(p for song in sources.get('ddr_world', {}).get('songs', [])
                         for chart in song['charts']
                         if (p := effective_jacket(song, chart)) and is_ddr_jacket(p))
        # Include orphan DDR artwork in full mode without inventing song metadata.
        if mode == 'full':
            paths.update(e['path'][19:] for e in tree if e['type'] == 'blob'
                         and e['path'].startswith('src/assets/jackets/')
                         and is_ddr_jacket(e['path'][19:])
                         and PurePosixPath(e['path']).suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'))
        failures = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(get, 'src/assets/jackets/' + p): p for p in sorted(paths)}
            for count, future in enumerate(as_completed(futures), 1):
                try:
                    future.result()
                except Exception as exc:
                    failures.append(dict(jacket=futures[future], error=str(exc)))
                if count % 100 == 0:
                    print(f'Jackets: {count}/{len(paths)}', flush=True)
        catalog['assets'] = {p: dict(path=str((cache / 'src/assets/jackets' / p).relative_to(root)),
                                         sha256=checksums['src/assets/jackets/' + p])
                             for p in sorted(paths) if 'src/assets/jackets/' + p in checksums}
        catalog['failures'] = failures
        catalog['source_checksums'] = {s: checksums[f'src/songs/{s}.json'] for s in sources}
        catalog['upstream_updated'] = {s: d['meta'].get('lastUpdated') for s, d in sources.items()}
        out = root / ('full.json' if mode == 'full' else f'{event}.json')
        dump_json(out, catalog)
        return out, catalog
    finally:
        dump_json(checksums_path, checksums)


def resolve_chart(catalog, song_id, style, difficulty, level=None):
    dataset = catalog['metadata_dataset']
    rows = [(r, c) for r in catalog['records'] if r['dataset'] == dataset and r['song_id'] == song_id
            for c in r['charts'] if (c['style'], c['difficulty']) == (style, difficulty)
            and (level is None or c['level'] == level)]
    # Identical duplicate rows are harmless. Conflicting versions are not.
    values = {(c['level'], c['max_ex'], c['max_ex_source']) for _, c in rows}
    return _chart_result(values, catalog['mode'], catalog['commit'])


def _chart_result(values, mode, commit):
    if not values:
        return dict(status='chart_outside_pool' if mode == 'event' else 'chart_unavailable', max_ex=None)
    if len(values) != 1:
        return dict(status='ambiguous_chart', max_ex=None)
    metadata_level, value, source = next(iter(values))
    return dict(status='matched' if value is not None else 'missing_max_ex', max_ex=value,
                source_dataset=source, source_commit=commit, metadata_level=metadata_level)


class ChartIndex:
    """Snapshot of the selected dataset, with the same joins as resolve_chart."""
    def __init__(self, catalog):
        grouped = {}
        for row in catalog['records']:
            if row['dataset'] != catalog['metadata_dataset']:
                continue
            for chart in row['charts']:
                key = (row['song_id'], chart['style'], chart['difficulty'])
                value = (chart['level'], chart['max_ex'], chart['max_ex_source'])
                grouped.setdefault((*key, None), set()).add(value)
                if chart['level'] is not None:
                    grouped.setdefault((*key, chart['level']), set()).add(value)
        self._resolved = {key:_chart_result(values, catalog['mode'], catalog['commit'])
                          for key, values in grouped.items()}
        self._missing = _chart_result(set(), catalog['mode'], catalog['commit'])

    def resolve(self, song_id, style, difficulty, level=None):
        # Each response owns its dictionary; callers cannot mutate the cached view.
        return self._resolved.get((song_id, style, difficulty, level), self._missing).copy()

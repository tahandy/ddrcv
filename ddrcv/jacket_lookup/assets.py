"""Explicit provisioning and immutable, offline runtime bundles."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from . import catalog
from .config import assets_root, catalog_path, selection_key, validate_config
from .archive import CatalogArchive, write_archive
from .features import build_index, PortableEncoder
from .lookup import Lookup
from .selection import project_catalog, SelectedCharts

PACKAGE_ASSETS = Path(__file__).parent / 'assets'


def profile():
    return catalog.read_json(PACKAGE_ASSETS / 'gallery-portable.json')


def legacy_profile():
    # Retain the exact profile and encoder of already prepared catalogs.
    return catalog.read_json(PACKAGE_ASSETS / 'gallery.json')


def qualified_profile(fingerprint):
    for frozen in (profile(), legacy_profile()):
        if fingerprint == frozen['gallery_fingerprint']:
            return frozen
    raise ValueError('Catalog uses an unqualified artwork gallery')


def _archive(path):
    return CatalogArchive(path, profile(), compatible_profiles=(legacy_profile(),))



@contextmanager
def preparation_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.prepare.lock').open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            if not stream.read(1):
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError('Catalog preparation is already running') from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError('Catalog preparation is already running') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _matches(selection, cfg):
    data = selection['catalog']
    if data['mode'] != cfg['mode'] or (cfg['mode'] == 'event' and data['event'] != cfg['event']):
        raise ValueError('Catalog selection does not match configuration; select its event/full mode or another file')


def _load_archive(path, cfg):
    with _archive(path) as archive:
        selection = archive.selection
        _matches(selection, cfg)
        lookup = Lookup.from_bytes(*archive.gallery(), thresholds=archive.profile)
        lookup._charts = SelectedCharts(selection)
        lookup.selection = selection
        lookup.bundle_info = version_info(selection, archive.pointer())
        return lookup


def _publish(destination, metadata, arrays, selection, cfg):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.' + uuid4().hex + '.tmp')
    try:
        write_archive(temporary, metadata, arrays, selection,
                      qualified_profile(selection['gallery_fingerprint']))
        # The complete candidate must pass the same offline qualification as a client.
        verified = _load_archive(temporary, cfg)
        del verified
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _pack_legacy(cfg):
    root, destination = assets_root(cfg), catalog_path(cfg)
    pointer = catalog.read_json(root / 'active' / (selection_key(cfg) + '.json'))
    selection = _selection(root, pointer, cfg)
    selection.update(gallery_fingerprint=pointer['gallery'], bundle_id=pointer['bundle'],
                     packed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    directory = root / 'galleries' / pointer['gallery']
    _publish(destination, (directory / 'index.json').read_bytes(),
             (directory / 'vectors.npz').read_bytes(), selection, cfg)


def pack(config=None):
    """Convert an existing folder catalog offline without deleting its contents."""
    cfg = validate_config(config)
    with preparation_lock(assets_root(cfg)):
        if not catalog_path(cfg).exists():
            _pack_legacy(cfg)
        return check(cfg)


def prepare(config=None, *, refresh=False, ref=None, source_root=None, progress=None):
    """Provision or refresh one portable catalog; keep the old file on failure."""
    cfg = validate_config(config)
    root, destination = assets_root(cfg), catalog_path(cfg)
    report = progress or (lambda message: None)
    with preparation_lock(root):
        frozen = profile()
        if destination.exists() and not refresh and ref is None:
            return check(cfg)
        legacy = root / 'active' / (selection_key(cfg) + '.json')
        if not destination.exists() and legacy.exists() and not refresh and ref is None:
            report('Converting the prepared catalog to a single file')
            _pack_legacy(cfg)
            return check(cfg)
        sources = Path(source_root) if source_root is not None else root / 'sources'
        if destination.exists():
            # A receiving client can refresh metadata using the gallery in its file.
            with _archive(destination) as archive:
                frozen = archive.profile
                _matches(archive.selection, cfg)
                metadata, arrays = archive.gallery()
        else:
            gallery_dir = root / 'galleries' / frozen['gallery_fingerprint']
            if not gallery_dir.exists():
                report('Downloading pinned DDR artwork')
                path, data = catalog.prepare(sources, mode='full', ref=frozen['source_commit'])
                if data['failures']:
                    raise ValueError('Artwork download incomplete; retry preparation')
                stage = root / 'staging' / uuid4().hex
                report('Encoding and verifying the full DDR gallery')
                build_index(path, stage, encoder_factory=PortableEncoder)
                verified = Lookup(stage, thresholds=frozen)
                del verified
                gallery_dir.parent.mkdir(parents=True, exist_ok=True)
                stage.replace(gallery_dir)
            metadata = (gallery_dir / 'index.json').read_bytes()
            arrays = (gallery_dir / 'vectors.npz').read_bytes()
        gallery = Lookup.from_bytes(metadata, arrays, thresholds=frozen)
        report('Downloading and pinning chart metadata')
        selected_slug = cfg['event'] if cfg['mode'] == 'event' else 'ddr_world'
        _, data = catalog.prepare(sources, mode='event', event=selected_slug, ref=ref or 'HEAD',
                                  include_world_artwork=True)
        if data['failures']:
            raise ValueError('Event artwork download incomplete; retry preparation')
        if cfg['mode'] == 'full':
            data.update(mode='full', event=None, metadata_dataset='ddr_world')
        world_source = catalog.read_json(sources / 'cache' / data['commit'] / 'src/songs/ddr_world.json')
        aliases = catalog.normalize_catalog({'ddr_world': world_source}, commit=data['commit'])['records']
        selected = project_catalog(gallery.meta, data, alias_records=aliases)
        del gallery
        selected.update(gallery_fingerprint=frozen['gallery_fingerprint'], bundle_id=uuid4().hex,
                        prepared_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        selected['packed_at'] = selected['prepared_at']
        report('Writing and validating the portable catalog')
        _publish(destination, metadata, arrays, selected, cfg)
        report('Ready')
        return check(cfg)


def _selection(root, pointer, config):
    import re
    if pointer.get('schema') != 1 or not re.fullmatch('[0-9a-f]{32}', pointer.get('bundle', '')):
        raise ValueError('Invalid catalog bundle')
    qualified_profile(pointer.get('gallery'))
    data_path = root / 'bundles' / pointer['bundle'] / 'selection.json'
    if catalog.sha256(data_path.read_bytes()) != pointer['selection_sha256']:
        raise ValueError('Catalog selection checksum mismatch')
    selection = catalog.read_json(data_path)
    _matches(selection, config)
    return selection


def version_info(selection, pointer):
    data = selection['catalog']
    updated = data.get('upstream_updated', {}).get(data['metadata_dataset'])
    if isinstance(updated, (int, float)):
        try:
            updated = datetime.fromtimestamp(updated / 1000, timezone.utc).isoformat(timespec='seconds')
        except (ValueError, OverflowError, OSError):
            updated = None
    return dict(mode=data['mode'], event=data['event'], commit=data['commit'],
                dataset=data['metadata_dataset'], dataset_updated_at=updated,
                prepared_at=selection.get('prepared_at'), packed_at=selection.get('packed_at'), bundle=pointer['bundle'],
                gallery=pointer['gallery'], gallery_commit=qualified_profile(pointer['gallery'])['source_commit'],
                selection_sha256=pointer['selection_sha256'])


def describe(config=None):
    """Inspect prepared metadata offline without loading image arrays or OCR.

    This reports the bundle on disk; it is not a replacement for readiness checks
    and is independent of the bundle retained by an active recognition session.
    """
    cfg = validate_config(config)
    root = assets_root(cfg)
    destination = catalog_path(cfg)
    info = dict(available=False, assets_dir=str(root), catalog_file=str(destination),
                mode=cfg['mode'], event=cfg['event'])
    try:
        if destination.exists():
            with _archive(destination) as archive:
                selection, pointer = archive.selection, archive.pointer()
            storage_format = 'ddrcatalog'
            _matches(selection, cfg)
        elif cfg['catalog_file']:
            raise FileNotFoundError(destination)
        else:
            pointer = catalog.read_json(root / 'active' / (selection_key(cfg) + '.json'))
            selection = _selection(root, pointer, cfg)
            storage_format = 'directory'
        info.update(version_info(selection, pointer), available=True, storage_format=storage_format,
                    needs_conversion=storage_format == 'directory',
                    unsupported_count=len(selection['unsupported']))
    except FileNotFoundError:
        info['error'] = 'No prepared catalog file at this location'
    except Exception as exc:
        info['error'] = str(exc)
    return info


def _load(root, pointer, config):
    selection = _selection(root, pointer, config)
    lookup = Lookup(root / 'galleries' / pointer['gallery'],
                    thresholds=qualified_profile(pointer['gallery']))
    lookup._charts = SelectedCharts(selection)
    lookup.selection = selection
    lookup.bundle_info = version_info(selection, pointer)
    return lookup


def load(config=None):
    cfg = validate_config(config)
    root = assets_root(cfg)
    destination = catalog_path(cfg)
    if destination.exists() or cfg['catalog_file']:
        lookup = _load_archive(destination, cfg)
    else:
        pointer = catalog.read_json(root / 'active' / (selection_key(cfg) + '.json'))
        lookup = _load(root, pointer, cfg)
    if cfg['difficulty_method'] == 'template':
        from .difficulty import DifficultyTemplates
        DifficultyTemplates(PACKAGE_ASSETS / 'templates')
    else:
        lookup._get_recognizer().warmup()
    return lookup


def check(config=None):
    cfg = validate_config(config)
    try:
        lookup = load(cfg)
        data = lookup.selection['catalog']
        return dict(ok=True, phase='ready', mode=data['mode'], event=data['event'],
                    commit=data['commit'], gallery=lookup.bundle_info['gallery'],
                    unsupported=lookup.selection['unsupported'],
                    ambiguous_songs=len(lookup.selection['blocked_song_ids']),
                    catalog_info={**lookup.bundle_info, 'catalog_file': str(catalog_path(cfg)),
                                  'storage_format': 'ddrcatalog' if catalog_path(cfg).exists() else 'directory',
                                  'available': True})
    except Exception as exc:
        return dict(ok=False, phase='unavailable', error=str(exc),
                    instruction='Prepare this catalog before enabling song recognition')


def processor(config=None, *, lookup=None):
    from .threaded import ThreadedSplashLookup
    from .difficulty import DifficultyTemplates
    cfg = validate_config(config)
    lookup = lookup if lookup is not None else load(cfg)
    return SelectedProcessor(lookup, cfg, ThreadedSplashLookup,
                             DifficultyTemplates(PACKAGE_ASSETS / 'templates')
                             if cfg['difficulty_method'] == 'template' else None)


class SelectedProcessor:
    def __init__(self, lookup, config, factory, difficulty_reader):
        self.lookup = lookup
        self.config = config
        self.worker = factory(lookup, difficulty_reader=difficulty_reader, high_qos=config['high_qos'])
        self.selection = lookup.selection

    def analyze(self, frame, *, style='single', confirmed_song=None, remaining_players=None):
        result = self.worker.analyze(frame, style=style, confirmed_song=confirmed_song,
                                     remaining_players=remaining_players)
        if result.get('accepted') and self.lookup.entries[result['song']['index']]['sha256'] in self.selection['blocked_artwork']:
            result.update(accepted=False, reason='ambiguous_artwork', song=None)
            for chart in result['players'].values():
                chart.update(status='song_unconfirmed', max_ex=None)
        return result

    def close(self, timeout=1):
        return self.worker.close(timeout)

    def threads(self):
        return (self.worker._difficulty.thread,)

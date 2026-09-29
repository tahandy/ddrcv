"""A portable catalog container. No extraction, pickle, or runtime network access."""
from io import BytesIO
import json
from pathlib import Path
import zipfile

import numpy as np

from .catalog import sha256

FORMAT = 'ddrcv.catalog'
VERSION = 1
LIMITS = {'manifest.json': 16384, 'profile.json': 16384,
          'selection.json': 128 * 1024**2, 'gallery/index.json': 128 * 1024**2,
          'gallery/vectors.npz': 512 * 1024**2}
PAYLOADS = set(LIMITS) - {'manifest.json'}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


class CatalogArchive:
    def __init__(self, path, expected_profile, *, compatible_profiles=()):
        self.zip = zipfile.ZipFile(path, 'r')
        try:
            entries = self.zip.infolist()
            names = [e.filename for e in entries]
            if len(names) != len(set(names)) or set(names) != set(LIMITS):
                raise ValueError('Unexpected or duplicate catalog entries')
            for entry in entries:
                if entry.file_size > LIMITS[entry.filename] or entry.flag_bits & 1:
                    raise ValueError('Catalog entry exceeds supported limits or is encrypted')
            self.manifest = json.loads(self.zip.read('manifest.json'))
            if self.manifest.get('format') != FORMAT or self.manifest.get('version') != VERSION:
                raise ValueError('Unsupported catalog container version')
            if set(self.manifest.get('files', {})) != PAYLOADS:
                raise ValueError('Incomplete catalog manifest')
            self.profile = json.loads(self.read('profile.json'))
            if self.profile not in (expected_profile, *compatible_profiles):
                raise ValueError('Catalog uses an unqualified matching profile')
            self.selection_bytes = self.read('selection.json')
            self.selection = json.loads(self.selection_bytes)
            if self.selection.get('gallery_fingerprint') != self.profile['gallery_fingerprint']:
                raise ValueError('Catalog selection uses a different artwork gallery')
        except BaseException:
            self.zip.close()
            raise

    def read(self, name):
        data = self.zip.read(name)
        record = self.manifest['files'][name]
        if len(data) != record['bytes'] or sha256(data) != record['sha256']:
            raise ValueError('Catalog checksum mismatch: ' + name)
        return data

    def gallery(self):
        metadata, arrays = self.read('gallery/index.json'), self.read('gallery/vectors.npz')
        self._validate_array_headers(json.loads(metadata), arrays)
        return metadata, arrays

    @staticmethod
    def _validate_array_headers(metadata, data):
        count = len(metadata['entries'])
        if not 0 < count <= 10000 or metadata['method'] != 'classical' or metadata['size'] != 128:
            raise ValueError('Unsupported catalog gallery dimensions')
        expected = {'vectors.npy': ((count, 2880), np.dtype('<f4')),
                    'images.npy': ((count, 128, 128, 3), np.dtype('u1'))}
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            if len(names) != 2 or set(names) != set(expected):
                raise ValueError('Unexpected catalog arrays')
            for name, (shape, dtype) in expected.items():
                with archive.open(name) as stream:
                    version = np.lib.format.read_magic(stream)
                    readers = {(1, 0): np.lib.format.read_array_header_1_0,
                               (2, 0): np.lib.format.read_array_header_2_0}
                    if version not in readers:
                        raise ValueError('Unsupported array encoding')
                    actual, fortran, actual_dtype = readers[version](stream, max_header_size=4096)
                    if actual != shape or actual_dtype != dtype or fortran:
                        raise ValueError('Catalog array shape or dtype mismatch')
                    required = int(np.prod(shape)) * dtype.itemsize + stream.tell()
                    if archive.getinfo(name).file_size != required:
                        raise ValueError('Catalog array length mismatch')

    def pointer(self):
        return dict(bundle=self.selection.get('bundle_id', self.manifest['files']['selection.json']['sha256'][:32]),
                    gallery=self.profile['gallery_fingerprint'],
                    selection_sha256=self.manifest['files']['selection.json']['sha256'])

    def close(self):
        self.zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def write_archive(path, metadata, arrays, selection, profile):
    """Write a candidate only; the caller validates it before atomic publication."""
    payloads = {'gallery/index.json': metadata, 'gallery/vectors.npz': arrays,
                'selection.json': json_bytes(selection), 'profile.json': json_bytes(profile)}
    manifest = dict(format=FORMAT, version=VERSION,
                    files={name: dict(bytes=len(data), sha256=sha256(data)) for name, data in payloads.items()})
    with zipfile.ZipFile(Path(path), 'w') as archive:
        for name, data in payloads.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_STORED if name.endswith('.npz') else zipfile.ZIP_DEFLATED)
        archive.writestr('manifest.json', json_bytes(manifest), compress_type=zipfile.ZIP_DEFLATED)

"""Classical CPU descriptors and portable indexes."""
from __future__ import annotations

import math
from pathlib import Path
import time

import cv2
import numpy as np

from .catalog import dump_json, read_json, sha256
from .images import read_image

METHODS = ('classical',)


def unit(vector):
    vector = np.asarray(vector, np.float32).reshape(-1)
    norm = np.linalg.norm(vector)
    return vector / max(float(norm), 1e-12)


def resize(image, size):
    # A shared image plane makes the native low-resolution catalog the bottleneck,
    # rather than asking an encoder to match incompatible sampling grids.
    return cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA
                      if max(image.shape[:2]) >= size else cv2.INTER_LINEAR)


def portable_unit(vector):
    """Normalize with a fixed reduction tree, independent of BLAS CPU dispatch.

    Float32 products are exact in float64. Explicit pairs fix addition order;
    normalization rounds once to float32, as the original encoder did.
    """
    vector = np.asarray(vector, np.float32).reshape(-1)
    terms = np.square(vector, dtype=np.float64)
    while len(terms) > 1:
        if len(terms) % 2:
            terms = np.append(terms, 0.)
        terms = terms[::2] + terms[1::2]
    norm = np.float32(math.sqrt(float(terms[0]))) if len(terms) else np.float32(0.)
    return vector / max(float(norm), 1e-12)


def classical(image):
    small = resize(image, 24).astype(np.float32) / 255
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    color = small - small.mean()
    edges = np.stack((cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)))
    return unit(np.concatenate((unit(color)*.85, unit(edges)*.35)))


def portable_classical(image):
    # Wide intermediates make these sums exact for their float32 inputs, avoiding
    # CPU-dependent reduction/FMA rounding in NumPy mean and OpenCV gray/Sobel.
    small = resize(image, 24).astype(np.float32) / 255
    color = small - np.float32(small.mean(dtype=np.float64))
    wide = small.astype(np.float64)
    gray = (wide[..., 0]*float(np.float32(.114)) +
            wide[..., 1]*float(np.float32(.587)) +
            wide[..., 2]*float(np.float32(.299))).astype(np.float32).astype(np.float64)
    edges = np.stack((cv2.Sobel(gray, cv2.CV_64F, 1, 0),
                      cv2.Sobel(gray, cv2.CV_64F, 0, 1))).astype(np.float32)
    return portable_unit(np.concatenate((portable_unit(color)*.85, portable_unit(edges)*.35)))


class Encoder:
    def __init__(self, method='classical', size=128, model_dir=None):
        if method != 'classical' or size not in (128, 150):
            raise ValueError('Production jacket lookup supports the classical descriptor only')
        self.method, self.size = method, size
        self.fingerprint = 'color-gradient-v1'
        cv2.setNumThreads(1)

    def encode(self, image):
        if image.shape[:2] != (self.size, self.size):
            image = resize(image, self.size)
        return classical(image)


class PortableEncoder(Encoder):
    """Qualified deterministic builder/query encoder; v1 remains readable."""
    fingerprint = 'color-gradient-portable-v1'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fingerprint = type(self).fingerprint

    def encode(self, image):
        if image.shape[:2] != (self.size, self.size):
            image = resize(image, self.size)
        return portable_classical(image)


def build_index(catalog_path, out, *, method='classical', size=128, model_dir=None, encoder_factory=Encoder):
    catalog_path, out = Path(catalog_path), Path(out)
    catalog = read_json(catalog_path)
    began = time.perf_counter()
    encoder = encoder_factory(method, size, model_dir)
    init_seconds = time.perf_counter()-began
    assets = {}
    for path, asset in catalog['assets'].items():
        assets.setdefault(asset['sha256'], []).append(path)
    references = {}
    for song in catalog['records']:
        for chart in song['charts']:
            references.setdefault(chart['jacket'], {})[song['song_id']] = song['name']
    entries, vectors, thumbnails, skipped = [], [], [], []
    for count, (digest, paths) in enumerate(sorted(assets.items()), 1):
        asset = catalog['assets'][paths[0]]
        local = catalog_path.parent / asset['path']
        if sha256(local.read_bytes()) != digest:
            raise ValueError(f'Jacket checksum mismatch: {local}')
        image = read_image(local)
        # Historical non-square banners are retained in catalog provenance but
        # cannot be stretched into jackets and called supported splash artwork.
        if abs(image.shape[0]/image.shape[1]-1) > .05:
            skipped.append(dict(paths=paths, reason='non_square_banner', shape=list(image.shape[:2])))
            continue
        songs = {}
        for p in paths:
            songs.update(references.get(p, {}))
        entries.append(dict(paths=paths, sha256=digest, songs=songs,
                            original_size=list(image.shape[:2])))
        vectors.append(encoder.encode(image))
        thumbnails.append(resize(image, size))
        if count % 250 == 0:
            print(f'{method}/{size}: {count}/{len(assets)} assets', flush=True)
    if not entries:
        raise ValueError('No supported jacket images')
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / 'vectors.npz', vectors=np.asarray(vectors, np.float32),
                        images=np.asarray(thumbnails, np.uint8))
    meta = dict(schema=1, method=method, size=size, fingerprint=encoder.fingerprint,
                catalog_sha256=sha256(catalog_path.read_bytes()), catalog=catalog,
                entries=entries, skipped=skipped, model_init_seconds=init_seconds,
                build_seconds=time.perf_counter()-began)
    meta['arrays_sha256'] = sha256((out / 'vectors.npz').read_bytes())
    dump_json(out / 'index.json', meta)
    return meta

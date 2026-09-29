"""Portable identity for every input that can affect gallery matching."""
import hashlib
import json

import numpy as np

MATCHING = dict(version=1, shortlist=16, border=4, gray_weight=.8,
                color_weight=.2, ranking='numpy-argsort-score-index-desc-v1')


def gallery_fingerprint(meta, vectors, images):
    payload = dict(matching=MATCHING, method=meta['method'], size=meta['size'],
                   encoder=meta['fingerprint'],
                   entries=[dict(sha256=e['sha256'], paths=e['paths'],
                                 songs=list(e['songs'].items())) for e in meta['entries']])
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':')).encode('utf-8'))
    for value in (vectors, images):
        array = np.ascontiguousarray(value, dtype=value.dtype.newbyteorder('<'))
        digest.update(str((array.dtype.str, array.shape)).encode('ascii'))
        digest.update(memoryview(array).cast('B'))
    return digest.hexdigest()

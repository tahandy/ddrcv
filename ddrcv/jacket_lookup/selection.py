"""Conservative event metadata projection onto an immutable artwork gallery."""
from collections import defaultdict
from copy import deepcopy

from .catalog import ChartIndex, normalize


def _keys(original):
    for field in ('saHash', 'saIndex'):
        if original.get(field):
            yield (field, str(original[field]))
    yield ('meta', normalize(original.get('name')), normalize(original.get('artist')))


def _compatible(left, right):
    common = [f for f in ('saHash', 'saIndex') if left.get(f) and right.get(f)]
    if common:
        return all(left[f] == right[f] for f in common)
    return (normalize(left.get('name')), normalize(left.get('artist'))) == (
        normalize(right.get('name')), normalize(right.get('artist')))


def project_catalog(gallery, selected, *, alias_records=()):
    """Keep chart records intact; only attach proven gallery identities/support."""
    candidates = defaultdict(list)
    for row in gallery['catalog']['records']:
        for key in _keys(row['original']):
            candidates[key].append(row)
    artwork = {e['sha256']: set(e['songs']) for e in gallery['entries']}
    owners = {digest: set(ids) for digest, ids in artwork.items()}
    path_digests = {p: e['sha256'] for e in gallery['entries'] for p in e['paths']}
    # Downloaded event bytes take precedence over the old path's bytes.
    path_digests.update({p: a['sha256'] for p, a in selected.get('assets', {}).items()})

    def bridge(row):
        rows = {r['record_id']: r for key in _keys(row['original'])
                for r in candidates.get(key, ())}
        ids = {r['song_id'] for r in rows.values()
               if _compatible(row['original'], r['original'])}
        return next(iter(ids)) if len(ids) == 1 else None

    output = deepcopy(selected)
    unsupported = []
    for row in output['records']:
        sid = bridge(row)
        old_sid = row['song_id']
        row['source_song_id'] = old_sid
        row['song_id'] = sid or 'unsupported:' + old_sid
        for chart in row['charts']:
            digest = selected.get('assets', {}).get(chart['jacket'], {}).get('sha256')
            reason = ('unsupported_identity' if sid is None else
                      'unsupported_artwork' if digest not in artwork or sid not in artwork[digest] else None)
            if reason:
                chart['unavailable_reason'] = reason
                unsupported.append(dict(record_id=row['record_id'], difficulty=chart['difficulty'],
                                        style=chart['style'], reason=reason))
            if digest in owners:
                owners[digest].add(sid or 'unsupported:' + old_sid)
    # New WORLD/event aliases sharing a known jacket must not establish unique identity.
    for row in alias_records:
        sid = bridge(row) or 'unsupported:' + row['song_id']
        for chart in row['charts']:
            digest = path_digests.get(chart['jacket'])
            if digest in owners:
                owners[digest].add(sid)
    blocked = sorted({sid for ids in owners.values() if len(ids) > 1
                      for sid in ids if not sid.startswith('unsupported:')})
    return dict(catalog=output, blocked_song_ids=blocked,
                blocked_artwork=sorted(digest for digest, ids in owners.items() if len(ids) > 1),
                unsupported=unsupported)


class SelectedCharts:
    def __init__(self, selection):
        self.catalog = selection['catalog']
        self.base = ChartIndex(self.catalog)
        self.unavailable = defaultdict(set)
        for row in self.catalog['records']:
            for chart in row['charts']:
                reason = chart.get('unavailable_reason')
                if reason:
                    self.unavailable[(row['song_id'], chart['style'], chart['difficulty'])].add(reason)

    def resolve(self, song_id, style, difficulty, level=None):
        reasons = self.unavailable.get((song_id, style, difficulty))
        if reasons:
            return dict(status=sorted(reasons)[0], max_ex=None)
        return self.base.resolve(song_id, style, difficulty, level)

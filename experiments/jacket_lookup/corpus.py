"""Reproducible splash discovery and inspection artifacts, independent of retrieval."""
from __future__ import annotations

import hashlib
from pathlib import Path
import time

import cv2
import numpy as np

from .catalog import dump_json

from ddrcv.jacket_lookup.images import JACKET_ROI, DIFFICULTY_ROIS, crop, read_image, write_image

def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def extract(video_dir, out, *, sample_hz=2):
    from .splash import SplashDetector

    out = Path(out)
    detector = SplashDetector()
    manifest = dict(schema=1, jacket_roi=JACKET_ROI, difficulty_rois=DIFFICULTY_ROIS,
                    discovery_hz=sample_hz, videos=[], samples=[], excluded=[])
    for path in sorted(Path(video_dir).glob('*.mkv')):
        if 'trimmed' in path.stem.lower():
            manifest['excluded'].append(dict(file=path.name, reason='overlapping_trim'))
            continue
        began = time.perf_counter()
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError(f'Cannot decode {path}')
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        step = max(1, round(fps / sample_hz))
        hits, negatives = [], []
        negative_targets = {int(count * frac) // step * step for frac in (.1, .5, .9)}
        index = 0
        while cap.grab():
            if index % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    raise ValueError(f'Cannot decode frame {index} in {path}')
                if frame.shape[:2] != (720, 1280):
                    raise ValueError(f'Expected 1280x720 game footage: {path}')
                matched, _ = detector.match(frame[..., ::-1])
                if matched:
                    hits.append(index)
                elif index in negative_targets:
                    negatives.append((index, frame))
            index += 1
        groups = []
        for idx in hits:
            if not groups or idx - groups[-1][-1] > step * 2:
                groups.append([])
            groups[-1].append(idx)
        for number, group in enumerate(groups):
            # Pick the sharpest central detector-positive frame, not the best match.
            middle = group[len(group)//4:max(len(group)//4+1, 3*len(group)//4)]
            candidates = []
            for idx in middle:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, frame = cap.read()
                if ok:
                    sharpness = cv2.Laplacian(cv2.cvtColor(crop(frame), cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
                    candidates.append((sharpness, idx, frame))
            if not candidates:
                continue
            _, selected, frame = max(candidates, key=lambda row: row[0])
            sample_id = f'{path.stem}_{number:02d}'
            relative = f'frames/{sample_id}.png'
            write_image(out / relative, frame)
            write_image(out / 'jackets' / f'{sample_id}.png', crop(frame))
            for player, roi in enumerate(DIFFICULTY_ROIS, 1):
                write_image(out / 'difficulty' / f'{sample_id}_p{player}.png', crop(frame, roi))
            _, presence = detector.match(frame[..., ::-1])
            row = dict(id=sample_id, video=path.name, kind='clean', frame=selected,
                       seconds=selected/fps, interval=[group[0]/fps, group[-1]/fps],
                       image=relative, presence=presence, label=None)
            manifest['samples'].append(row)
            for suffix, idx in [('entry', max(0, group[0]-step)), ('exit', min(count-1, group[-1]+step))]:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, other = cap.read()
                if ok:
                    relative = f'frames/{sample_id}_{suffix}.png'
                    write_image(out / relative, other)
                    manifest['samples'].append(dict(id=f'{sample_id}_{suffix}', parent=sample_id,
                        video=path.name, kind='transition', frame=idx, seconds=idx/fps, image=relative, label=None))
        for number, (idx, frame) in enumerate(negatives):
            sample_id = f'{path.stem}_negative{number}'
            relative = f'frames/{sample_id}.png'
            write_image(out / relative, frame)
            manifest['samples'].append(dict(id=sample_id, video=path.name, kind='negative',
                frame=idx, seconds=idx/fps, image=relative, label=None))
        cap.release()
        manifest['videos'].append(dict(file=path.name, sha256=file_hash(path), fps=fps,
            reported_frames=count, decoded_frames=index, splash_intervals=len(groups),
            scan_seconds=time.perf_counter()-began))
        dump_json(out / 'manifest.json', manifest)
        print(f'{path.name}: {len(groups)} splashes; {index} frames; {time.perf_counter()-began:.1f}s', flush=True)
    contact_sheet(manifest, out)
    return manifest


def contact_sheet(manifest, out):
    from PIL import Image, ImageDraw
    out = Path(out)
    rows = manifest['samples']
    for page in range(0, len(rows), 16):
        sheet = Image.new('RGB', (1280, 16//4*215), '#202020')
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(rows[page:page+16]):
            x, y = (i % 4)*320, (i//4)*215
            with Image.open(out / row['image']) as im:
                sheet.paste(im.resize((320, 180)), (x, y))
            draw.text((x+3, y+182), row['id'], fill='white')
            draw.text((x+3, y+197), f"{row['kind']} {row['seconds']:.2f}s", fill='white')
        sheet.save(out / f'contact_{page//16:02d}.jpg')

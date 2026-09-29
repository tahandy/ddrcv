"""Template-bank construction for the research corpus."""
from pathlib import Path
from ddrcv.jacket_lookup.difficulty import *
from .catalog import dump_json, read_json, sha256
from .corpus import read_image, write_image

def build_bank(corpus, labels_path, out):
    corpus, out = Path(corpus), Path(out)
    if (out/'bank.json').exists():
        raise FileExistsError('Template bank exists; use a new output directory')
    truth = read_json(labels_path)['labels']
    entries = []
    for difficulty, (sample, player, rect) in SOURCES.items():
        label = truth[sample]
        if label['players'][player]['difficulty'] != difficulty or not label['verified']:
            raise ValueError('Template source requires verified matching difficulty')
        path = corpus/'difficulty'/f'{sample}_{player}.png'
        image = read_image(path)
        x, y, w, h = rect
        template = (text_mask(image)[y:y+h, x:x+w]*255).astype(np.uint8)
        target = out/f'{difficulty}.png'
        write_image(target, template)
        write_image(out/f'{difficulty}-source.png', image[y:y+h, x:x+w])
        entries.append(dict(difficulty=difficulty, image=target.name,
            sha256=sha256(target.read_bytes()), sample=sample, player=player,
            song_id=label['song_id'], source_sha256=sha256(path.read_bytes()), rect=rect))
    bank = dict(schema=1, preprocess=PREPROCESS, layout='WORLD-1280x720', entries=entries,
                labels_sha256=sha256(Path(labels_path).read_bytes()), thresholds=None)
    dump_json(out/'bank.json', bank)
    return bank

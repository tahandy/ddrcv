import os
from collections import OrderedDict
import numpy as np
from PIL.FontFile import WIDTH

from ddrcv.ocr import get_best_match_from_results, get_ocr_singleton

os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

import time
import cv2

_WIDTH = 200
_HEIGHT = 32

CONFIG_P1 = {
    'bb_name': [63, 464, _WIDTH, _HEIGHT],
    'bb_difficulty': [63, 496, _WIDTH, _HEIGHT + 4]
}


CONFIG_P2 = {
    'bb_name': [1216-_WIDTH, 464, _WIDTH, _HEIGHT],
    'bb_difficulty': [1216-_WIDTH, 496, _WIDTH, _HEIGHT + 4]
}


def extract_chip(image, bb, upsample=1, do_blur=False, do_invert=False):
    chip = image[bb[1]:bb[1]+bb[3], bb[0]:bb[0]+bb[2], :].copy()

    if do_invert:
        chip = cv2.bitwise_not(chip)

    if upsample > 1:
        chip = cv2.resize(chip, None, fx=upsample, fy=upsample, interpolation=cv2.INTER_LINEAR_EXACT)

    if do_blur:
        chip = cv2.blur(chip, (2, 2))

    return chip


class PlayerParser:
    def __init__(self, ocr_parser, config, do_name, do_difficulty):
        self.parser = ocr_parser
        self.config = config
        self.do_name = do_name
        self.do_difficulty = do_difficulty

    def parse(self, image):
        output = dict()
        if self.do_name:
            output['name'] = self._parse_name(image)
        if self.do_difficulty:
            output['difficulty'] = self._parse_difficulty(image)
        return output

    def _parse_name(self, image):
        chip = extract_chip(image, self.config['bb_name'], do_invert=True, upsample=1)
        result = self.parser.readtext(chip, canvas_size=256, adjust_contrast=1)
        if result:
            return result[0][1]
        return None

    def _parse_difficulty(self, image):
        chip = extract_chip(image, self.config['bb_difficulty'], do_invert=True, upsample=1)
        result = self.parser.readtext(chip, canvas_size=256)
        possible_values = ['beginner', 'basic', 'difficult', 'expert', 'challenge']
        if result:
            best_match = get_best_match_from_results(result, possible_values, lower=True)
            return best_match[0].upper() + best_match[1:]
        return None


class SplashParser:
    def __init__(self, ocr_parser, database, do_name=False):
        self.parser = ocr_parser
        self.database = database
        self.p1 = PlayerParser(self.parser, CONFIG_P1, do_name=do_name, do_difficulty=True)
        self.p2 = PlayerParser(self.parser, CONFIG_P2, do_name=do_name, do_difficulty=True)
        self.jacket_bb = [425, 105, 854 - 425, 534 - 105]

    def parse(self, image, player_presence=(True, True)):
        confidence, song = self._lookup_song(image)
        p1_results = self.p1.parse(image) if player_presence[0] else None
        p2_results = self.p2.parse(image) if player_presence[1] else None

        if p1_results is not None:
            notes, freeze, _ = song.song_data['Single'][p1_results['difficulty']]
            p1_results['max_ex_score'] = 3 * (notes + freeze)

        if p2_results is not None:
            notes, freeze, _ = song.song_data['Single'][p2_results['difficulty']]
            p2_results['max_ex_score'] = 3 * (notes + freeze)

        output = {
            'song': str(song.song_data['Song']),
            'song_confidence': float(confidence),
            'p1': p1_results,
            'p2': p2_results
        }
        return output

    def _lookup_song(self, image):
        # Need to convert it to RGB from BGR
        jacket = extract_chip(image, self.jacket_bb)
        jacket - jacket[..., ::-1].copy()
        similarity, song = self.database.lookup(jacket)
        return similarity[0], song[0]


if __name__ == "__main__":
    from pprint import pprint
    from ddrcv.jacket_database.database.database import DatabaseLookup

    reader = get_ocr_singleton()  # this needs to run only once to load the model into memory
    img = cv2.imread('../../state_images/song_splash_updated_p2.png', cv2.IMREAD_UNCHANGED)

    # cv2.imshow('tmp', img)
    # cv2.waitKey(0)

    database = DatabaseLookup.from_prebuilt('../jacket_database/output/db_effnetb0.pkl')
    parser = SplashParser(reader, database, do_name=False)

    tic = time.time()
    pprint(parser.parse(img, player_presence=(False, True)))
    print(f'Results parsing took {time.time() - tic:.3f} seconds')

import os
from collections import OrderedDict
import numpy as np

from ddrcv.ocr import get_best_match_from_results, get_ocr_singleton

os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

import time
import cv2


CONFIG_P1 = {
    'bb_name': [243, 88, 463-243, 114-88],
    'score_topleft': [134, 432],
    'bb_difficulty': [243, 117, 463-243, 152-117]
}


CONFIG_P2 = {
    'bb_name': [817, 88, 1037-817, 114-88],
    'score_topleft': [650, 432],
    'bb_difficulty': [817, 117, 1037-817, 152-117]
}


CONFIG_SCORE_BOX = {
    'column_y_offsets': {
        'max_combo': 42,
        'marvelous': 65,
        'perfect': 84,
        'great': 105,
        'good': 124,
        'ok': 142,
        'miss': 161
    },
    'height': 20,
    'x': 222,
    'width': 48,
    'ex_score_tl': (366, 161),
    'fast_tl': [286, 85],
    'slow_tl': [356, 85]
}


def parse_scores(parser, image, config, box_offset, upsample=1, do_blur=False, do_invert=True, padding=0):
    # Assemble all bounding boxes between the vertical column of scores and the offshoots
    boxes = OrderedDict()
    for key, y_offset in config['column_y_offsets'].items():
        bb = [box_offset[0] + config['x'], box_offset[1] + y_offset, config['width'], config['height']]
        boxes[key] = bb

    boxes['ex_score'] = [box_offset[0] + config['ex_score_tl'][0], box_offset[1] + config['ex_score_tl'][1], config['width'], config['height']]
    boxes['fast'] = [box_offset[0] + config['fast_tl'][0], box_offset[1] + config['fast_tl'][1], config['width'], config['height']]
    boxes['slow'] = [box_offset[0] + config['slow_tl'][0], box_offset[1] + config['slow_tl'][1], config['width'], config['height']]

    # Pad the bounding boxes if desired
    if padding > 0:
        for key, bb in boxes.items():
            bb_new = [bb[0] - padding, bb[1] - padding, bb[2] + 2 * padding, bb[3] + 2 * padding]
            boxes[key] = bb_new

    # Extract uniformly sized chips for every element, and perform pre-processing tasks,
    # and stack them into a (B, height, width, channel) tensor
    chips = []
    for bb in boxes.values():
        chip = extract_chip(image, bb, upsample=upsample, do_blur=do_blur, do_invert=do_invert)
        chips.append(chip)
    chips = np.stack(chips, axis=0)

    # Perform batched processing -- additionally, decreasing the canvas size speeds things up
    result = parser.readtext_batched(chips, canvas_size=128)

    # Reformat the output into a dict of element_tag: integer_numeral
    collated = OrderedDict()
    for res, key in zip(result, boxes.keys()):
        # In the event the OCR fails to find a value, set it to -1 so that at least I know it failed
        value = -1
        if len(res) > 0:
            value = int(res[0][1])
        collated[key] = value

    return collated


def extract_chip(image, bb, upsample=1, do_blur=False, do_invert=False):
    chip = image[bb[1]:bb[1]+bb[3], bb[0]:bb[0]+bb[2], :]

    if do_invert:
        chip = cv2.bitwise_not(chip)

    if upsample > 1:
        chip = cv2.resize(chip, None, fx=upsample, fy=upsample, interpolation=cv2.INTER_LINEAR_EXACT)

    if do_blur:
        chip = cv2.blur(chip, (2, 2))

    return chip


class PlayerParser:
    def __init__(self, ocr_parser, config):
        self.parser = ocr_parser
        self.config = config
        self._exists = False

    @property
    def exists(self):
        return self._exists

    def parse(self, image):
        name = self._parse_name(image)
        if name is None:
            return
        self._exists = True
        difficulty = self._parse_difficulty(image)
        scores = self._parse_scores(image)

        output = {
            'name': name,
            'difficulty': difficulty,
            'scores': scores
        }
        return output

    def _parse_name(self, image):
        chip = extract_chip(image, self.config['bb_name'], do_invert=True)
        result = self.parser.readtext(chip, canvas_size=256)
        print('name result: ', result)
        if result:
            return result[0][1]
        return None

    def _parse_difficulty(self, image):
        chip = extract_chip(image, self.config['bb_difficulty'], do_invert=True, upsample=1)
        result = self.parser.readtext(chip, canvas_size=128)
        print('difficulty result: ', result)
        possible_values = ['beginner', 'basic', 'difficult', 'expert', 'challenge']
        if result:
            best_match = get_best_match_from_results(result, possible_values, lower=True)
            return best_match[0].upper() + best_match[1:]
        return None

    def _parse_scores(self, image):
        return parse_scores(self.parser,
                            image,
                            CONFIG_SCORE_BOX,
                            self.config['score_topleft'],
                            upsample=3,
                            do_blur=True,
                            do_invert=True,
                            padding=4)


class ResultsParser:
    def __init__(self, ocr_parser, database):
        self.parser = ocr_parser
        self.database = database
        self.p1 = PlayerParser(self.parser, CONFIG_P1)
        self.p2 = PlayerParser(self.parser, CONFIG_P2)

    def parse(self, image):
        song = self._lookup_song(image)
        stage = self._parse_stage(image)
        p1_results = self.p1.parse(image)
        p2_results = self.p2.parse(image)

        output = dict()
        output['stage'] = stage
        if song:
            output['song'] = song.song_data['Song']
        if p1_results:
            output['p1'] = p1_results
        if p2_results:
            output['p2'] = p2_results
        return output

    def _lookup_song(self, image):
        if self.database:
            # Need to convert it to RGB from BGR
            jacket = image[108:318, 535:744, ::-1].copy()
            _, song = self.database.lookup(jacket)
            return song[0]
        return None

    def _parse_stage(self, image):
        bb = [523, 67, 759-523, 100-67]
        chip = extract_chip(image, bb, do_invert=True, upsample=1)
        result = self.parser.readtext(chip, canvas_size=128)
        print('stage result: ', result)
        return result[0][1]


if __name__ == "__main__":
    from pprint import pprint
    from ddrcv.jacket_database.database.database import DatabaseLookup

    reader = get_ocr_singleton()  # this needs to run only once to load the model into memory
    img = cv2.imread('../state_images/results_updated.png', cv2.IMREAD_UNCHANGED)


    database = DatabaseLookup.from_prebuilt('../ddrcv/jacket_database/output/db_effnetb0.pkl')
    parser = ResultsParser(reader, database)

    tic = time.time()
    pprint(parser.parse(img))
    print(f'Results parsing took {time.time() - tic:.3f} seconds')

    # img = cv2.bitwise_not(img)
    # img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # bb_p1_name = [243, 88, 463-243, 114-88]
    # bb_p2_name = [817, 88, 1037-817, 114-88]
    # bb = bb_p2_name
    #
    # bb = [878, 473, 923-878, 611-473]
    #
    #
    # score_tl = CONFIG_P2['score_topleft']
    # bb = [score_tl[0] + 229, score_tl[1] + 42, 271 - 228, 180-42]
    #
    # p1_name_chip = img[bb[1]:bb[1]+bb[3], bb[0]:bb[0]+bb[2], :]
    # upsample = 4
    # p1_name_chip = cv2.resize(p1_name_chip, None, fx=upsample, fy=upsample, interpolation=cv2.INTER_LINEAR_EXACT)
    # p1_name_chip = cv2.blur(p1_name_chip, (2, 2))
    #
    # # bb = CONFIG_P2['bb_difficulty']
    # # p1_name_chip = img[bb[1]:bb[1]+bb[3], bb[0]:bb[0]+bb[2], :]
    #
    # chip = p1_name_chip
    #
    # cv2.imshow('p1 name', chip)
    # cv2.waitKey(0)
    #
    # for _ in range(1):
    #     tic = time.time()
    #     result = reader.readtext(chip)#, adjust_contrast=1.0)
    #     print(f'readtext took {time.time() - tic} seconds')
    #     print(result)
    #
    # # Result points are top-left, top-right, bottom-right, bottom-left [x, y]
    # for res in result:
    #     pts, value, score = res
    #
    #     for (px, py), color in zip(pts, [(255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255)]):
    #         cv2.circle(chip, (px, py), 5, color=color)
    #
    #     # initial_tl = (bb_p1_name[0] + pts[0][0] // 4, bb_p1_name[1] + pts[0][1] // 4)
    #     # initial_br = (bb_p1_name[0] + pts[2][0] // 4 + 1, bb_p1_name[1] + pts[2][1] // 4 + 1)
    #
    #     tl = pts[0]
    #     br = pts[2]
    #     text_bb = [tl[0], tl[1], br[0] - tl[0], br[1] - tl[1]]
    #     text_bb = [tmp // upsample for tmp in text_bb]
    #     text_bb = [229 + text_bb[0], 42 + text_bb[1], text_bb[2], text_bb[3]]
    #
    #     print(value, text_bb)
    #
    #     # print(initial_tl[0], initial_tl[1], initial_br[0] - initial_tl[0], initial_br[1] - initial_tl[1])
    #
    #
    # cv2.imshow('test', chip)
    #
    # # cv2.circle(p1_name_chip, )
    # cv2.waitKey(0)
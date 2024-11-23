import time
from pathlib import Path
from enum import IntFlag
from pprint import pprint
from typing import Tuple

import cv2
from matplotlib import pyplot as plt

from ddrcv.score.glyph_detector import GlyphLoader, GlyphDetector
from video_frame_extractor import VideoFrameExtractor


def detections_to_num(detections):
    if not detections:
        return -1

    sorted_by_x = sorted(detections, key=lambda x: x['location'][0])
    num = int(''.join([x['glyph_class'] for x in sorted_by_x]))
    return num


class SingleScoreExtractor:
    """
    Given a set of numeral glyphs, a region of interest, and a full RGB image frame
    this class will extract the numerical string found inside the ROI
    """
    def __init__(self, roi_bb, glyph_dir=None):
        """
        :param roi_bb: 4-tuple of (top, left, height, width)
        :param glyph_dir: Location of glyph files 0.png ... 9.png. Will default to `score/fonts/World`
        """
        # Load glyph paths (You need to provide actual file paths to your glyph images)
        if glyph_dir is None:
            glyph_dir = Path(__file__).parent / 'fonts' / 'World2'
        print('Loading glyphs from ', glyph_dir)
        glyph_paths = {str(ii): str(glyph_dir / f'{ii}.png') for ii in range(10)}

        # Load the glyphs
        glyph_loader = GlyphLoader(glyph_paths)
        glyphs = glyph_loader.glyphs

        # Initialize the detector
        self.detector = GlyphDetector(glyphs, threshold=0.9, scale=1.0, dilation=2)
        self.roi_bb = roi_bb

        # self.detector.set_optimal_scale(0.942)
        # self.detector.set_optimal_scale(1)

    def extract(self, frame_rgb, debug=False):
        target = frame_rgb[self.roi_bb[0]:self.roi_bb[0] + self.roi_bb[2], self.roi_bb[1]:self.roi_bb[1] + self.roi_bb[3], ...]

        # Detect glyphs
        # tic = time.time()
        detected_glyphs = self.detector.detect_glyphs(target)
        detected_num = detections_to_num(detected_glyphs)
        # print(f'Extracted score in {1000*(time.time() - tic)} ms')
        if debug:
            return detected_num, detected_glyphs
        return detected_num, None


class ScoreExtractor:
    """
    Given a set of numeral glyphs, a region of interest, and a full RGB image frame
    this class will extract the numerical string found inside the ROI
    """
    p1_roi = [645 - 1, 160, 45, 240]
    p2_roi = [645 - 1, 880, 45, 240]

    def __init__(self, glyph_dir=None):
        """
        :param present: 2ple consisting of (p1_present, p2_present) bool values
        :param glyph_dir: Location of glyph files 0.png ... 9.png. Will default to `score/fonts/World`
        """
        self.p1_present = True
        self.p2_present = True
        self.p1_extractor = SingleScoreExtractor(ScoreExtractor.p1_roi, glyph_dir=glyph_dir)
        self.p2_extractor = SingleScoreExtractor(ScoreExtractor.p2_roi, glyph_dir=glyph_dir)

    def set_presence(self, p1_present, p2_present):
        self.p1_present = p1_present
        self.p2_present = p2_present

    def extract(self, frame_rgb, debug=False):
        p1_score, p1_debug = None, None
        p2_score, p2_debug = None, None

        if self.p1_present:
            p1_score, p1_debug = self.p1_extractor.extract(frame_rgb, debug=debug)
        if self.p2_present:
            p2_score, p2_debug = self.p2_extractor.extract(frame_rgb, debug=debug)

        output = {
            "data": {
                "p1_score": p1_score,
                "p2_score": p2_score
            }
        }

        if debug:
            output['debug'] = {
                "p1_debug": p1_debug,
                "p2_debug": p2_debug
            }

        return output



if __name__ == "__main__":
    video_file = Path(r"C:\code\ddr_ex_parser\videos\yukopi.mp4")
    output_file = 'yukopi_detected.mp4'

    # print(video_file.exists())
    # extractor = VideoFrameExtractor(str(video_file))
    #
    # start_frame = extractor.get_frame_index_by_time(30)
    # frames = extractor.preload_frames(start_frame, start_frame + 60)
    frames = [cv2.imread('../../score_p2.png')]

    # Crop image
    x_offset = 970
    y_offset = 850
    width = 1250 - 970
    height = 925 - 850

    p1_roi = [645, 160, 45, 240]
    p2_roi = [645, 880, 45, 240]
    # p1_score = SingleScoreExtractor(p1_roi)
    # p2_score = SingleScoreExtractor(p2_roi)
    extractor = ScoreExtractor()
    extractor.set_presence(False, True)

    # for frame_idx in range(frame_start, frame_end + 1):
    for image in frames:
        # image = extractor.get_frame_by_index(frame_idx)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Detect glyphs
        # tic = time.time()
        # p1_result = p1_score.extract(image, debug=True)
        # p2_result = p2_score.extract(image, debug=True)
        result = extractor.extract(image, debug=True)

        p1_detected_num, p1_detected_glyphs = result['data']['p1_score'], result['debug']['p1_debug']
        p2_detected_num, p2_detected_glyphs = result['data']['p2_score'], result['debug']['p2_debug']

        # print(detected_glyphs)
        print(p1_detected_num)
        print(p2_detected_num)


        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        cv2.rectangle(image, (p2_roi[1], p2_roi[0]), (p2_roi[1] + p2_roi[3], p2_roi[0] + p2_roi[2]), (0, 255, 0), 2)
        cv2.rectangle(image, (p1_roi[1], p1_roi[0]), (p1_roi[1] + p1_roi[3], p1_roi[0] + p1_roi[2]), (0, 255, 0), 2)

        # Visualize the results
        for roi, detected_glyphs in zip([p1_roi, p2_roi], [p1_detected_glyphs, p2_detected_glyphs]):
            if detected_glyphs is None:
                continue
            for glyph in detected_glyphs:
                cv2.rectangle(image, (glyph['bounding_box'][0] + roi[1], glyph['bounding_box'][1] + roi[0]),
                              (glyph['bounding_box'][2] + roi[1], glyph['bounding_box'][3] + roi[0]), (0, 255, 0), 2)
                cv2.putText(image, glyph['glyph_class'], (glyph['bounding_box'][0] + roi[1], glyph['bounding_box'][1] - 10 + roi[0]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        # print(detected_num)
        # cv2.putText(image, str(detected_num), (1250, 925),
        #             cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 4)


        plt.imshow(image[..., ::-1])
        plt.show()

        # out.write(image)

    # out.release()

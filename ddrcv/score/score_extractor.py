import time
from pathlib import Path

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


class ScoreExtractor:
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
            glyph_dir = Path(__file__).parent / 'fonts' / 'World'
        print('Loading glyphs from ', glyph_dir)
        glyph_paths = {str(ii): str(glyph_dir / f'{ii}.png') for ii in range(10)}

        # Load the glyphs
        glyph_loader = GlyphLoader(glyph_paths)
        glyphs = glyph_loader.glyphs

        # Initialize the detector
        self.detector = GlyphDetector(glyphs, threshold=0.8, scale_range=(0.8, 1.1))
        self.roi_bb = roi_bb

        self.detector.set_optimal_scale(0.942)

    def extract(self, frame_rgb, debug=False):
        target = frame_rgb[self.roi_bb[0]:self.roi_bb[0] + self.roi_bb[2], self.roi_bb[1]:self.roi_bb[1] + self.roi_bb[3], ...]

        # Detect glyphs
        tic = time.time()
        detected_glyphs = self.detector.detect_glyphs(target)
        detected_num = detections_to_num(detected_glyphs)
        print(f'Extracted score in {1000*(time.time() - tic)} ms')
        if debug:
            return detected_num, detected_glyphs
        return detected_num


if __name__ == "__main__":
    video_file = Path(r"C:\code\ddr_ex_parser\videos\yukopi.mp4")
    output_file = 'yukopi_detected.mp4'

    print(video_file.exists())
    extractor = VideoFrameExtractor(str(video_file))

    start_frame = extractor.get_frame_index_by_time(30)
    frames = extractor.preload_frames(start_frame, start_frame + 60)

    # Crop image
    x_offset = 970
    y_offset = 850
    width = 1250 - 970
    height = 925 - 850

    p1_roi = [645, 160, 45, 240]
    p2_roi = [645, 880, 45, 240]
    p1_score = ScoreExtractor(p1_roi)
    p2_score = ScoreExtractor(p2_roi)

    # for frame_idx in range(frame_start, frame_end + 1):
    for image in frames:
        # image = extractor.get_frame_by_index(frame_idx)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Detect glyphs
        # tic = time.time()
        p1_detected_num, p1_detected_glyphs = p1_score.extract(image, debug=True)
        p2_detected_num, p2_detected_glyphs = p2_score.extract(image, debug=True)
        # print(detected_glyphs)
        print(p1_detected_num)
        print(p2_detected_num)


        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        cv2.rectangle(image, (p2_roi[1], p2_roi[0]), (p2_roi[1] + p2_roi[3], p2_roi[0] + p2_roi[2]), (0, 255, 0), 2)
        cv2.rectangle(image, (p1_roi[1], p1_roi[0]), (p1_roi[1] + p1_roi[3], p1_roi[0] + p1_roi[2]), (0, 255, 0), 2)

        # Visualize the results
        for roi, detected_glyphs in zip([p1_roi, p2_roi], [p1_detected_glyphs, p2_detected_glyphs]):
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

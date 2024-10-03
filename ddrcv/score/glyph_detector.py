import cv2
import numpy as np
import matplotlib.pyplot as plt

def apply_contrast(input_img, contrast = 0):
    buf = input_img
    if contrast != 0:
        f = 131*(contrast + 127)/(127*(131-contrast))
        alpha_c = f
        gamma_c = 127*(1-f)

        buf = cv2.addWeighted(input_img, alpha_c, input_img, 0, gamma_c)

    return buf

def preprocess_image(image):
    """
    Preprocess the RGB image by maximizing contrast and binarizing it, considering only pure white pixels.

    :param image: The RGB image to be preprocessed.
    :return: The preprocessed binary image.
    """
    # Convert to grayscale
    # gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Maximize contrast
    # contrast_maximized = maximize_contrast(gray)
    contrast_maximized = apply_contrast(image, contrast=127)
    binary = np.min(contrast_maximized, axis=-1) > 250
    binary = (binary * 255).astype(np.uint8)

    # Thresholding to consider only white pixels
    # Since we're focusing on (255, 255, 255) in RGB, we look for the max value in grayscale
    # _, binary = cv2.threshold(contrast_maximized, 254, 255, cv2.THRESH_BINARY)

    return binary


class GlyphLoader:
    def __init__(self, glyph_paths):
        """
        Load glyphs from file paths and store them with their alpha channels for masking.

        :param glyph_paths: Dictionary of glyph paths with keys being the glyph class (e.g., '0', '1')
                            and values being the file paths to the glyph images.
        """
        self.glyphs = self.load_glyphs(glyph_paths)

    def load_glyphs(self, glyph_paths):
        """
        Load the glyph images with alpha channel and store them in a dictionary.

        :param glyph_paths: Dictionary of glyph file paths.
        :return: Dictionary with keys as glyph classes and values as tuple (glyph image, alpha mask).
        """
        glyphs = {}
        for glyph_class, path in glyph_paths.items():
            glyph = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if glyph is None:
                raise ValueError(f"Failed to load glyph image from path: {path}")

            # Split the image into grayscale and alpha channel
            gray = glyph[:, :, 0]  # Assuming the image is grayscale with alpha
            alpha = glyph[:, :, 3]
            gray[alpha < 255] = 0
            glyphs[glyph_class] = (gray, alpha)

        return glyphs


class GlyphDetector:
    def __init__(self, glyphs, scale_range=(0.5, 2.0), scale_steps=20, threshold=0.8):
        """
        Initialize the GlyphDetector with glyphs, scale settings, and detection threshold.

        :param glyphs: Dictionary of glyphs with their alpha masks.
        :param scale_range: Range of scales to apply during detection.
        :param scale_steps: Number of steps in the scale range.
        :param threshold: Matching threshold.
        """
        self.glyphs = glyphs
        self.scale_range = scale_range
        self.scale_steps = scale_steps
        self.threshold = threshold
        self.optimal_scale = None

    def set_optimal_scale(self, optimal_scale):
        """
        Set the optimal scale to be used during detection.

        :param optimal_scale: The optimal scaling factor to freeze.
        """
        self.optimal_scale = optimal_scale

    def find_optimal_scale(self, image):
        """
        Determine the optimal scale that maximizes the correlation value across multiple calls.

        :param image: The target image to be analyzed.
        :return: The optimal scaling factor.
        """
        max_corr = -np.inf
        best_scale = None

        image = preprocess_image(image)

        for scale in np.linspace(self.scale_range[0], self.scale_range[1], self.scale_steps):
            avg_corr = 0
            for glyph_class, (glyph, alpha) in self.glyphs.items():
                scaled_glyph = cv2.resize(glyph, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                scaled_alpha = cv2.resize(alpha, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

                result = self._match_glyph(image, scaled_glyph, mask=scaled_alpha)
                avg_corr += result.max()

            avg_corr /= len(self.glyphs)

            if avg_corr > max_corr:
                max_corr = avg_corr
                best_scale = scale

        self.optimal_scale = best_scale
        return best_scale

    def detect_glyphs(self, image):
        """
        Detect glyphs in the given image.

        :param image: The target image where glyphs are to be found.
        :return: List of detected glyphs with their location, scale, and class.
        """

        # print(self.find_optimal_scale(image))

        image = preprocess_image(image)

        # cv2.imshow('blah', image)
        # cv2.waitKey(0)

        if self.optimal_scale:
            scales = [self.optimal_scale]
        else:
            scales = np.linspace(self.scale_range[0], self.scale_range[1], self.scale_steps)

        detected_glyphs = []

        for scale in scales:
            for glyph_class, (glyph, alpha) in self.glyphs.items():
                scaled_glyph = cv2.resize(glyph, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                # scaled_alpha = cv2.resize(alpha, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

                res = self._match_glyph(image, scaled_glyph)

                # Threshold the matches
                loc = np.where(res >= self.threshold)

                for pt in zip(*loc[::-1]):
                    detected_glyphs.append({
                        'glyph_class': glyph_class,
                        'location': pt,
                        'scale': scale,
                        'match_value': res[pt[1], pt[0]],
                        'bounding_box': (pt[0], pt[1], pt[0] + scaled_glyph.shape[1], pt[1] + scaled_glyph.shape[0])
                    })

        detected_glyphs = sorted(detected_glyphs, key=lambda x: x['match_value'], reverse=True)

        # Apply Non-Maximum Suppression to remove overlapping boxes
        final_glyphs = self.non_maximum_suppression(detected_glyphs)

        return final_glyphs

    def _match_glyph(self, image, glyph, mask=None):
        """
        Perform masked template matching.

        :param image: The target image.
        :param glyph: The glyph template.
        :param mask: The alpha mask of the glyph.
        :return: The result of template matching.
        """
        # cv2.imshow('glyph', glyph)
        # cv2.waitKey(0)
        # cv2.imshow('mask', mask)
        # cv2.waitKey(0)
        if mask is not None:
            return cv2.matchTemplate(image, glyph, cv2.TM_CCORR_NORMED)
        else:
            return cv2.matchTemplate(image, glyph, cv2.TM_CCOEFF_NORMED)

    def non_maximum_suppression(self, detections, overlap_thresh=0.3):
        """
        Apply Non-Maximum Suppression (NMS) to remove overlapping detections.

        :param detections: List of detected glyphs with their bounding boxes.
        :param overlap_thresh: Overlap threshold for suppression.
        :return: List of final glyphs after applying NMS.
        """
        if len(detections) == 0:
            return []

        boxes = np.array([d['bounding_box'] for d in detections])
        scores = np.array([d['match_value'] for d in detections])

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]

        areas = (x2 - x1 + 1) * (y2 - y1 + 1)
        order = scores.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(detections[i])

            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            w = np.maximum(0, xx2 - xx1 + 1)
            h = np.maximum(0, yy2 - yy1 + 1)

            overlap = (w * h) / areas[order[1:]]

            order = order[np.where(overlap <= overlap_thresh)[0] + 1]

        return keep

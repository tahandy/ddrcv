"""Research adapter: production matcher with optional research encoders."""
from ddrcv.jacket_lookup.lookup import *
from ddrcv.jacket_lookup.lookup import Lookup as _Lookup
from .features import Encoder
import cv2
import numpy as np

class Lookup(_Lookup):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, encoder_factory=Encoder, **kwargs)
        self.sift = cv2.SIFT_create(nfeatures=300) if self.meta['method'] == 'sift' else None
        self.keypoints = []
        if self.sift:
            for im in self.images:
                self.keypoints.append(self.sift.detectAndCompute(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), None))

    def _geometry(self, query_features, index):
        qk, qd = query_features
        rk, rd = self.keypoints[index]
        if qd is None or rd is None or min(len(qd), len(rd)) < 4:
            return 0.0
        pairs = cv2.BFMatcher().knnMatch(qd, rd, k=2)
        good = [m for pair in pairs if len(pair) == 2 for m, n in [pair] if m.distance < .75*n.distance]
        if len(good) < 4:
            return 0.0
        a = np.float32([qk[m.queryIdx].pt for m in good])
        b = np.float32([rk[m.trainIdx].pt for m in good])
        cv2.setRNGSeed(20260929)
        transform, mask = cv2.findHomography(a, b, cv2.RANSAC, 3.0)
        if transform is None or mask is None or not np.isfinite(transform).all():
            return 0.0
        inliers = a[mask.ravel().astype(bool)]
        if len(inliers) < 4:
            return 0.0
        area = cv2.contourArea(cv2.convexHull(inliers)) / self.meta['size']**2
        # Four coincident points or one tiny text region are weak identity evidence.
        return float(min(1, len(inliers)/20) * min(1, area/.2) * len(inliers)/len(good))

    def _prepare_verification(self, query):
        if self.sift:
            return self.sift.detectAndCompute(cv2.cvtColor(query, cv2.COLOR_BGR2GRAY), None)
        if self.meta['method'] == 'classical':
            return super()._prepare_verification(query)
        return None

    def _verify_candidate(self, context, index, similarities):
        if self.sift:
            return self._geometry(context, index)
        if self.meta['method'] == 'classical':
            return super()._verify_candidate(context, index, similarities)
        return float(similarities[index])
